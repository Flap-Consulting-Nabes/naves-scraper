"""
Dashboard Streamlit para el scraper de naves industriales.

Secciones:
  - Resumen        — metricas generales
  - Control        — ejecutar / detener / sesion
  - Programacion   — configurar horario automatico
  - Registros      — ver log en tiempo real
  - Anuncios       — tabla de anuncios scraped
  - Webflow        — sincronizar con el CMS
"""
import os
import time
from datetime import datetime

import httpx
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")
API_KEY = os.getenv("API_SECRET_KEY", "")
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "")
if not DASHBOARD_PASSWORD:
    raise RuntimeError("DASHBOARD_PASSWORD no está configurada en .env — establece una contraseña segura antes de iniciar el dashboard.")


# -- Autenticacion -------------------------------------------------------

def check_password() -> bool:
    if st.session_state.get("authenticated"):
        return True

    st.markdown("## Naves Scraper — Acceso")
    with st.form("login_form"):
        pw = st.text_input("Contrasena", type="password")
        submitted = st.form_submit_button("Entrar")
        if submitted:
            if pw == DASHBOARD_PASSWORD:
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("Contrasena incorrecta")
    return False


# -- API helper ----------------------------------------------------------

def api(method: str, path: str, silent: bool = False, **kwargs) -> dict | None:
    try:
        r = httpx.request(
            method,
            f"{API_BASE}{path}",
            headers={"x-api-key": API_KEY},
            timeout=15.0,
            **kwargs,
        )
        r.raise_for_status()
        return r.json()
    except httpx.ConnectError:
        if not silent:
            st.error("No se puede conectar a la API. Comprueba que el servidor esta en marcha.")
        return None
    except httpx.HTTPStatusError as e:
        if not silent:
            try:
                error_data = e.response.json()
                detail = error_data.get("detail", str(e))
                st.error(f"Error {e.response.status_code}: {detail}")
            except Exception:
                st.error(f"Error de conexion: {e}")
        return None
    except Exception as e:
        if not silent:
            st.error(f"Error inesperado: {e}")
        return None


# -- Formateo ------------------------------------------------------------

def fmt_dt(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return iso


ESTADO_TEXTO = {
    "idle":    "Inactivo",
    "running": "En ejecucion",
    "error":   "Error",
    "stopped": "Detenido",
}


# -- Banner de bloqueo (aparece en todas las paginas) --------------------

def mostrar_alerta_sesion():
    """
    Muestra un aviso prominente si Milanuncios ha bloqueado la sesion.
    Incluye boton para renovar la sesion directamente.
    """
    sc = api("GET", "/api/scraper/status", silent=True) or {}
    if not sc.get("needs_session_renewal"):
        return

    sess = api("GET", "/api/session/status", silent=True) or {}
    sess_state = sess.get("state", "idle")

    st.error(
        "**Sesion bloqueada por Milanuncios**\n\n"
        "El scraper ha detectado un bloqueo (F5/Incapsula o Kasada). "
        "Es necesario renovar la sesion abriendo Chrome y completando el acceso manualmente.",
        icon=None,
    )

    if sess_state == "running":
        st.warning(
            "La renovacion de sesion esta en curso. "
            "Abre Chrome en el escritorio del servidor y completa el acceso."
        )
        if st.button("Actualizar estado de la sesion"):
            st.rerun()
    else:
        scraper_state = sc.get("state", "idle")
        if scraper_state == "running":
            st.warning("⚠️ **ATENCIÓN:** Debes detener el scraper en el panel de control antes de poder renovar la sesión.")
            st.button("Renovar sesion ahora", type="primary", disabled=True)
        else:
            col1, col2 = st.columns([2, 3])
            with col1:
                if st.button("Renovar sesion ahora", type="primary"):
                    r = api("POST", "/api/session/renew")
                    if r:
                        st.success(
                            "Chrome se ha abierto. "
                            "Ve al escritorio del servidor y completa el acceso a Milanuncios."
                        )
                        time.sleep(1)
                        st.rerun()
            with col2:
                if sess.get("last_error"):
                    st.caption(f"Ultimo intento: {sess['last_error']}")

    st.divider()


# -- Paginas -------------------------------------------------------------

def page_resumen():
    st.title("Resumen general")

    mostrar_alerta_sesion()

    wf = api("GET", "/api/webflow/status", silent=True) or {}
    sc = api("GET", "/api/scraper/status", silent=True) or {}

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total anuncios", wf.get("total", "—"))
    c2.metric("Sincronizados en Webflow", wf.get("synced", "—"))
    c3.metric("Pendientes de sync", wf.get("pending", "—"))
    state = sc.get("state", "idle")
    c4.metric("Estado del scraper", ESTADO_TEXTO.get(state, state))

    st.divider()

    col_izq, col_der = st.columns(2)

    with col_izq:
        st.subheader("Estado del scraper")
        if state == "running":
            st.info(
                f"Pagina actual: {sc.get('current_page', '?')}  \n"
                f"Anuncios nuevos: {sc.get('total_new', 0)}  \n"
                f"Duplicados saltados: {sc.get('total_skipped', 0)}"
            )
        elif state == "error":
            st.error(f"Error: {sc.get('last_error', 'desconocido')}")
        else:
            st.success("Inactivo y listo para ejecutar")

        if sc.get("started_at"):
            st.caption(f"Ultimo inicio: {fmt_dt(sc['started_at'])}")
        if sc.get("finished_at"):
            st.caption(f"Ultimo fin: {fmt_dt(sc['finished_at'])}")

    with col_der:
        st.subheader("Ultima sincronizacion Webflow")
        last_sync = wf.get("last_sync_at")
        if last_sync:
            st.info(f"Ultima sincronizacion: {fmt_dt(last_sync)}")
        else:
            st.warning("Aun no se ha sincronizado ningun anuncio")

    if state == "running":
        time.sleep(5)
        st.rerun()


def page_control():
    st.title("Control del Scraper")

    mostrar_alerta_sesion()

    status = api("GET", "/api/scraper/status") or {}
    state = status.get("state", "idle")

    st.subheader("Estado actual")
    estado_texto = ESTADO_TEXTO.get(state, state)
    if state == "running":
        st.info(
            f"Estado: **{estado_texto}**  \n"
            f"Pagina: {status.get('current_page', '?')} | "
            f"Nuevos: {status.get('total_new', 0)} | "
            f"Saltados: {status.get('total_skipped', 0)}"
        )
    elif state == "error":
        st.error(f"Estado: **{estado_texto}** — {status.get('last_error', '')}")
    else:
        st.success(f"Estado: **{estado_texto}**")

    if status.get("started_at"):
        st.caption(f"Inicio: {fmt_dt(status['started_at'])}  |  Fin: {fmt_dt(status.get('finished_at'))}")

    st.divider()
    st.subheader("Ejecutar el scraper")

    col1, col2 = st.columns(2)

    with col1:
        max_pages = st.number_input(
            "Maximo de paginas (0 = sin limite)", min_value=0, value=0, step=1
        )
        dry_run = st.checkbox("Modo prueba (no guarda en la base de datos)")
        reset = st.checkbox("Empezar desde la primera pagina")

        if st.button(
            "Iniciar scraper",
            disabled=(state == "running"),
            type="primary",
        ):
            r = api(
                "POST", "/api/scraper/run",
                json={"max_pages": max_pages, "dry_run": dry_run, "reset": reset},
            )
            if r:
                st.success("El scraper se ha iniciado correctamente")
                time.sleep(1)
                st.rerun()

    with col2:
        if st.button(
            "Detener scraper",
            disabled=(state != "running"),
            type="secondary",
        ):
            r = api("POST", "/api/scraper/stop")
            if r:
                st.warning("Se ha enviado la senal de parada")
                time.sleep(1)
                st.rerun()

    st.divider()
    st.subheader("Renovacion de sesion")
    st.markdown(
        "Si Milanuncios bloquea el scraper, es necesario renovar la sesion. "
        "Al pulsar el boton, se abre Chrome en el servidor para que puedas "
        "iniciar sesion manualmente."
    )

    sess = api("GET", "/api/session/status", silent=True) or {}
    sess_state = sess.get("state", "idle")

    if sess_state == "running":
        st.info(
            "La renovacion esta en curso. "
            "Ve al escritorio del servidor y completa el acceso a Milanuncios."
        )
        if st.button("Actualizar estado"):
            st.rerun()
    else:
        if sess.get("finished_at"):
            st.caption(f"Ultima renovacion: {fmt_dt(sess['finished_at'])}")
            if sess_state == "error":
                st.error(f"El ultimo intento fallo: {sess.get('last_error', '')}")
            else:
                st.success("La ultima renovacion se completo correctamente")
        else:
            st.caption("Sin renovaciones previas")

        if state == "running":
            st.warning("Debes detener el scraper antes de renovar la sesion.")
        elif st.button("Abrir Chrome para renovar sesion"):
            r = api("POST", "/api/session/renew")
            if r:
                st.rerun()

    if state == "running":
        time.sleep(5)
        st.rerun()


def page_programacion():
    st.title("Programacion automatica")

    mostrar_alerta_sesion()

    cfg = api("GET", "/api/cron") or {}
    current_expr = cfg.get("cron_expr", "0 6 * * *")
    current_max = cfg.get("max_pages", 0)
    next_run = cfg.get("next_run")

    if next_run:
        st.info(f"Proxima ejecucion programada: **{fmt_dt(next_run)}**")
    else:
        st.warning("No hay ninguna ejecucion programada")

    st.divider()

    PRESETS = {
        "Todos los dias a las 6:00":      "0 6 * * *",
        "Dos veces al dia (6h y 18h)":    "0 6,18 * * *",
        "Dias laborables a las 7:00":     "0 7 * * 1-5",
        "Cada 4 horas":                   "0 */4 * * *",
        "Cada hora":                      "0 * * * *",
        "Solo manual (sin programacion)": "",
        "Personalizado":                  current_expr,
    }

    preset_names = list(PRESETS.keys())
    default_preset = "Personalizado"
    for name, expr in PRESETS.items():
        if expr == current_expr and name != "Personalizado":
            default_preset = name
            break

    selected = st.selectbox("Horario predefinido", preset_names, index=preset_names.index(default_preset))
    cron_expr = st.text_input("Expresion cron", value=PRESETS[selected])
    max_pages_sched = st.number_input(
        "Maximo de paginas en ejecucion programada (0 = sin limite)",
        min_value=0, value=current_max, step=1,
    )

    if cron_expr:
        st.caption(
            "Formato: minuto hora dia-mes mes dia-semana  "
            "| Ejemplo: `0 6 * * *` = todos los dias a las 6:00"
        )

    if st.button("Guardar configuracion", type="primary"):
        r = api(
            "PUT", "/api/cron",
            json={"cron_expr": cron_expr, "max_pages": max_pages_sched},
        )
        if r:
            st.success(
                f"Configuracion guardada: {cron_expr or 'sin programacion'}"
                + (f" | Maximo de paginas: {max_pages_sched}" if max_pages_sched else "")
            )
            time.sleep(1)
            st.rerun()


def page_registros():
    st.title("Registros del scraper")

    mostrar_alerta_sesion()

    col1, col2 = st.columns([3, 1])
    lines = col1.slider("Numero de lineas a mostrar", 50, 1000, 300, step=50)
    auto_refresh = col2.checkbox("Actualizar cada 5 segundos", value=False)

    data = api("GET", "/api/logs", params={"lines": lines}) or {}
    log_lines = data.get("lines", [])

    if not log_lines:
        st.info("No hay registros todavia. Ejecuta el scraper para generar registros.")
    else:
        log_text = "\n".join(log_lines)
        st.code(log_text, language="text")
        st.caption(f"Mostrando las ultimas {len(log_lines)} lineas del archivo {data.get('file', 'logs/scraper.log')}")

    if auto_refresh:
        time.sleep(5)
        st.rerun()


def page_anuncios():
    st.title("Anuncios obtenidos")

    mostrar_alerta_sesion()

    with st.expander("Filtros de busqueda", expanded=False):
        col1, col2, col3, col4 = st.columns(4)
        province = col1.text_input("Provincia")
        min_surface = col2.number_input("Superficie minima (m2)", min_value=0, value=0)
        max_price = col3.number_input("Precio maximo (euros)", min_value=0, value=0)
        sort_by = col4.selectbox(
            "Ordenar por",
            ["scraped_at", "price_numeric", "surface_m2", "published_at"],
            format_func=lambda x: {
                "scraped_at": "Fecha de obtencion",
                "price_numeric": "Precio",
                "surface_m2": "Superficie",
                "published_at": "Fecha de publicacion",
            }.get(x, x),
        )

    if "listings_page" not in st.session_state:
        st.session_state.listings_page = 1

    params: dict = {
        "page": st.session_state.listings_page,
        "page_size": 50,
        "sort_by": sort_by,
        "sort_dir": "desc",
    }
    if province:
        params["province"] = province
    if min_surface:
        params["min_surface"] = min_surface
    if max_price:
        params["max_price"] = max_price

    data = api("GET", "/api/listings", params=params) or {}
    items = data.get("items", [])
    total = data.get("total", 0)
    total_pages = max(data.get("pages", 1), 1)

    st.caption(f"Total: **{total}** anuncios | Pagina {st.session_state.listings_page} de {total_pages}")

    if items:
        df = pd.DataFrame(items)
        display_cols = [
            "listing_id", "title", "province", "location",
            "price_numeric", "surface_m2", "price_per_m2",
            "ad_type", "scraped_at", "webflow_item_id",
        ]
        visible = [c for c in display_cols if c in df.columns]
        rename_map = {
            "listing_id": "ID",
            "title": "Titulo",
            "province": "Provincia",
            "location": "Localidad",
            "price_numeric": "Precio (euros)",
            "surface_m2": "Superficie (m2)",
            "price_per_m2": "Euros/m2",
            "ad_type": "Tipo",
            "scraped_at": "Fecha obtencion",
            "webflow_item_id": "ID en Webflow",
        }
        st.dataframe(
            df[visible].rename(columns=rename_map),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No hay anuncios con los filtros seleccionados.")

    pcol1, pcol2, pcol3 = st.columns([1, 2, 1])
    if pcol1.button("Anterior", disabled=st.session_state.listings_page <= 1):
        st.session_state.listings_page -= 1
        st.rerun()
    pcol2.markdown(
        f"<div style='text-align:center'>Pagina {st.session_state.listings_page} de {total_pages}</div>",
        unsafe_allow_html=True,
    )
    if pcol3.button("Siguiente", disabled=st.session_state.listings_page >= total_pages):
        st.session_state.listings_page += 1
        st.rerun()


def page_webflow():
    st.title("Sincronizacion con Webflow")

    mostrar_alerta_sesion()

    status = api("GET", "/api/webflow/status") or {}

    c1, c2, c3 = st.columns(3)
    c1.metric("Total anuncios", status.get("total", 0))
    c2.metric("Sincronizados", status.get("synced", 0))
    c3.metric("Pendientes", status.get("pending", 0))

    last_sync = status.get("last_sync_at")
    if last_sync:
        st.caption(f"Ultima sincronizacion: {fmt_dt(last_sync)}")

    st.divider()

    st.markdown(
        """
        Los anuncios se envian a Webflow como **borradores**.
        Para publicarlos, accede al editor de Webflow y publicalos manualmente.

        El proceso de sincronizacion:
        1. Sube las imagenes de cada anuncio a Webflow
        2. Crea la ficha del anuncio con todos los datos
        3. Marca el anuncio como sincronizado en la base de datos local
        """
    )

    pending = status.get("pending", 0)

    if pending == 0:
        st.success("Todos los anuncios ya estan sincronizados con Webflow")
    else:
        st.warning(f"Hay **{pending}** anuncio(s) pendientes de sincronizar")
        if st.button(
            f"Sincronizar {pending} anuncio(s) con Webflow",
            type="primary",
        ):
            r = api("POST", "/api/webflow/sync")
            if r:
                st.success(
                    "Sincronizacion iniciada. "
                    "Espera unos minutos y recarga la pagina para ver el resultado."
                )
                time.sleep(2)
                st.rerun()

    with st.expander("Informacion tecnica de la coleccion"):
        collection_id = os.getenv("WEBFLOW_COLLECTION_ID", "673373bb232280f5720b72ca")
        st.code(f"Collection ID: {collection_id}", language="text")
        st.markdown(
            "Para ver los campos disponibles en Webflow, ejecuta la sincronizacion "
            "una vez y revisa los registros del scraper."
        )


# -- Principal -----------------------------------------------------------

def check_session_notifications():
    """Comprueba cambios en el estado de la sesión y emite notificaciones flotantes (toasts)."""
    sess = api("GET", "/api/session/status", silent=True) or {}
    current_state = sess.get("state", "idle")
    
    # Comprobar si hay un estado anterior guardado en la sesión de Streamlit
    if "prev_sess_state" in st.session_state:
        prev_state = st.session_state["prev_sess_state"]
        
        # Transición: Renovación exitosa
        if prev_state == "running" and current_state == "idle":
            st.toast("✅ Sesión de Milanuncios renovada exitosamente", icon="🎉")
        
        # Transición: Error o navegador cerrado
        elif prev_state == "running" and current_state == "error":
            error_msg = sess.get("last_error", "Navegador cerrado o error inesperado")
            st.toast(f"❌ Fallo al renovar sesión: {error_msg}", icon="🚨")
            
    # Actualizar estado para la próxima recarga
    st.session_state["prev_sess_state"] = current_state


def main():
    st.set_page_config(
        page_title="Naves Scraper",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    if not check_password():
        st.stop()
        return

    # Comprobar notificaciones de sesión al cambiar de estado
    check_session_notifications()

    with st.sidebar:
        st.markdown("## Naves Scraper")
        st.divider()
        page = st.radio(
            "Seccion",
            [
                "Resumen",
                "Control del scraper",
                "Programacion",
                "Registros",
                "Anuncios",
                "Webflow",
            ],
            label_visibility="collapsed",
        )
        st.divider()
        if st.button("Cerrar sesion"):
            st.session_state.clear()
            st.rerun()

    pages = {
        "Resumen":           page_resumen,
        "Control del scraper": page_control,
        "Programacion":      page_programacion,
        "Registros":         page_registros,
        "Anuncios":          page_anuncios,
        "Webflow":           page_webflow,
    }
    pages[page]()


if __name__ == "__main__":
    main()
