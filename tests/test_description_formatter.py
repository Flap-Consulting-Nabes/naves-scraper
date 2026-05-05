"""Tests for utils.description_formatter (Iteración 2026-05, Tarea 4)."""
import pytest

from utils.description_formatter import format_description_html, strip_ref_prefix


class TestEmptyInputs:
    @pytest.mark.parametrize("value", [None, "", "   ", "\n\n", "\r\n"])
    def test_empty_returns_none(self, value):
        assert format_description_html(value) is None


class TestSingleParagraph:
    def test_plain_text_wrapped_in_p(self):
        assert format_description_html("Una nave grande.") == "<p>Una nave grande.</p>"

    def test_html_special_chars_escaped(self):
        out = format_description_html("Precio < 200 € & oferta")
        assert "&lt;" in out
        assert "&amp;" in out
        assert "<p>" in out  # the p tag itself is not escaped

    def test_single_newline_becomes_br(self):
        out = format_description_html("Linea uno\nLinea dos")
        assert out == "<p>Linea uno<br>Linea dos</p>"


class TestMultipleParagraphs:
    def test_blank_line_starts_new_paragraph(self):
        out = format_description_html("Parrafo uno.\n\nParrafo dos.")
        assert out == "<p>Parrafo uno.</p><p>Parrafo dos.</p>"

    def test_multiple_blank_lines_collapsed(self):
        out = format_description_html("A\n\n\n\nB")
        assert out == "<p>A</p><p>B</p>"


class TestBullets:
    def test_leading_bullets_become_ul(self):
        raw = "• Acceso amplio\n• Polígono industrial\n• Suministros disponibles"
        out = format_description_html(raw)
        assert out.startswith("<ul>")
        assert "<li>Acceso amplio</li>" in out
        assert "<li>Suministros disponibles</li>" in out

    def test_inline_bullets_split_paragraph_then_list(self):
        # Leading "Ref: 123." prefix gets stripped before rendering.
        raw = "Ref: 123. Una nave grande. • Acceso • Suministros • Vigilancia"
        out = format_description_html(raw)
        assert "Ref:" not in out
        assert "<p>Una nave grande.</p>" in out
        assert "<ul>" in out
        assert "<li>Acceso</li>" in out

    def test_single_bullet_does_not_trigger_list(self):
        # One stray bullet shouldn't turn a paragraph into a list
        raw = "Una opción • interesante."
        out = format_description_html(raw)
        assert "<ul>" not in out
        assert "<p>" in out

    def test_bullets_html_escaped(self):
        raw = "• <script>alert(1)</script>\n• Otro bullet"
        out = format_description_html(raw)
        assert "<script>" not in out
        assert "&lt;script&gt;" in out


class TestRealisticBenedictSample:
    """Mimics the screenshot description Benedict shared (truncated)."""

    def test_inline_bullets_with_long_lead_text_render_as_list(self):
        raw = (
            "Ref: 3396-12895. Oportunidad Única: Venta de 4 Naves. "
            "Caracteristicas de las Naves: • Superficie: 1.250 m². "
            "• Diseño Moderno: Estructura robusta. "
            "• Accesibilidad: Vial central."
        )
        out = format_description_html(raw)
        assert "<ul>" in out
        assert out.count("<li>") == 3
        # Ref prefix is stripped; the rest of the lead context remains.
        assert "Ref:" not in out
        assert "Oportunidad" in out


class TestStripRefPrefix:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Ref: 652-2936. Nave en ALBUJON.", "Nave en ALBUJON."),
            ("Ref: 109832692-JM-041. Ponemos a su disposición.",
             "Ponemos a su disposición."),
            ("REF: ABC123. Texto.", "Texto."),
            ("Referencia 12345 — Nave grande.", "Nave grande."),
            ("  Ref:  X1  .  Texto.", "Texto."),
        ],
    )
    def test_known_prefixes_stripped(self, raw, expected):
        assert strip_ref_prefix(raw) == expected

    def test_no_prefix_left_intact(self):
        text = "Nave industrial sin referencia inicial."
        assert strip_ref_prefix(text) == text

    def test_only_strips_at_start(self):
        # A "Ref:" appearing later in the body must not be touched.
        text = "Nave grande. Para más info Ref: 123 al teléfono."
        assert strip_ref_prefix(text) == text

    def test_strip_then_format_e2e(self):
        # End-to-end: real Don Benito-style description renders cleanly.
        raw = (
            "Ref: 109832692-JM-041. Ponemos a su disposición una céntrica "
            "nave con 902 m². Ofrecemos esta propiedad bajo una doble "
            "modalidad (venta o alquiler)."
        )
        out = format_description_html(raw)
        assert "Ref:" not in out
        assert out.startswith("<p>Ponemos a su disposición")
