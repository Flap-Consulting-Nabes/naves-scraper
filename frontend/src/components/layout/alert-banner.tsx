"use client";

import { TriangleAlert, RefreshCw, KeyRound, Monitor } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useScraperStatus } from "@/hooks/use-scraper-status";
import { useSessionStatus } from "@/hooks/use-session-status";
import { useChromePopup } from "@/hooks/use-chrome-popup";
import { renewSession, stopScraper, cancelSession } from "@/lib/api";
import { toast } from "sonner";
import { useState } from "react";

function getSessionSubLabel(s: { waiting_for_login?: boolean; login_detected?: boolean; navigating?: boolean } | null | undefined): string {
  if (!s) return "Renovando sesión...";
  if (s.waiting_for_login) return "Esperando inicio de sesión en Chrome...";
  if (s.login_detected) return "Login detectado, guardando sesión...";
  if (s.navigating) return "Navegando para verificar sesión...";
  return "Renovando sesión...";
}

export function AlertBanner() {
  const { status, isRunning, mutate } = useScraperStatus();
  const { session, isRenewing } = useSessionStatus();
  const { setOpen: openChrome, vncAvailable } = useChromePopup();
  const [starting, setStarting] = useState(false);

  const hasCaptcha = status?.challenge_waiting ?? false;
  const needsRenewal = status?.needs_session_renewal ?? false;

  async function handleCancel() {
    setStarting(true);
    try {
      await cancelSession();
      mutate();
      toast.info("Renovación de sesión cancelada.");
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setStarting(false);
    }
  }

  async function handleStopAndRenew() {
    setStarting(true);
    try {
      if (isRunning) await stopScraper();
      await renewSession();
      mutate();
      openChrome(true);
      toast.info("Chrome abierto. Completa el login para renovar la sesión.");
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setStarting(false);
    }
  }

  // Priority 1: captcha active
  if (hasCaptcha) {
    return (
      <div className="sticky top-0 z-30 flex items-center gap-3 border-b bg-amber-50 px-4 py-3 text-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
        <TriangleAlert className="mt-0.5 size-4 shrink-0" />
        <div className="flex-1 text-sm">
          <p className="font-medium">Captcha detectado</p>
          <p className="text-amber-700 dark:text-amber-300">
            Chrome está abierto en pantalla. Resuelve el captcha manualmente para que el scraper pueda continuar.
          </p>
        </div>
        <div className="flex shrink-0 gap-2">
          {vncAvailable && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => openChrome(true)}
              className="border-amber-400 text-amber-900 hover:bg-amber-100"
            >
              <Monitor className="mr-1.5 size-3.5" />
              Ver Chrome
            </Button>
          )}
          <Button
            size="sm"
            variant="outline"
            onClick={handleStopAndRenew}
            disabled={starting}
            className="border-amber-400 text-amber-900 hover:bg-amber-100"
          >
            Parar y renovar sesión
          </Button>
        </div>
      </div>
    );
  }

  // Priority 2: session renewal in progress
  if (needsRenewal && isRenewing) {
    const subLabel = getSessionSubLabel(session);
    return (
      <div className="sticky top-0 z-30 flex items-start gap-3 border-b bg-blue-50 px-4 py-3 text-blue-900 dark:bg-blue-950/40 dark:text-blue-200">
        <RefreshCw className="mt-0.5 size-4 shrink-0 animate-spin" />
        <div className="flex-1 text-sm">
          <p className="font-medium">Renovando sesión</p>
          {session?.waiting_for_login ? (
            <ol className="mt-1 space-y-0.5 text-blue-700 dark:text-blue-300 list-decimal list-inside">
              <li>Resuelve el captcha si aparece en Chrome</li>
              <li>Inicia sesión en tu cuenta de Milanuncios</li>
              <li>Ve a &quot;Mis Anuncios&quot; — el script lo detectará automáticamente</li>
            </ol>
          ) : (
            <p className="text-blue-700 dark:text-blue-300">{subLabel}</p>
          )}
        </div>
        <div className="flex shrink-0 gap-2">
          {vncAvailable && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => openChrome(true)}
              className="border-blue-400 text-blue-900 hover:bg-blue-100 dark:border-blue-600 dark:text-blue-200 dark:hover:bg-blue-900/40"
            >
              <Monitor className="mr-1.5 size-3.5" />
              Ver Chrome
            </Button>
          )}
          <Button
            size="sm"
            variant="outline"
            onClick={handleCancel}
            disabled={starting}
            className="border-blue-400 text-blue-900 hover:bg-blue-100 dark:border-blue-600 dark:text-blue-200 dark:hover:bg-blue-900/40"
          >
            Cancelar
          </Button>
        </div>
      </div>
    );
  }

  // Priority 3: session renewal needed but not started
  if (needsRenewal) {
    return (
      <div className="sticky top-0 z-30 flex items-center gap-3 border-b bg-red-50 px-4 py-3 text-red-900 dark:bg-red-950/40 dark:text-red-200">
        <KeyRound className="size-4 shrink-0" />
        <div className="flex-1 text-sm">
          <p className="font-medium">Sesión expirada o ban detectado</p>
          <p className="text-red-700 dark:text-red-300">
            Es necesario renovar la sesión de Chrome para continuar.
          </p>
        </div>
        <Button
          size="sm"
          variant="destructive"
          onClick={handleStopAndRenew}
          disabled={starting}
        >
          Abrir Chrome
        </Button>
      </div>
    );
  }

  return null;
}
