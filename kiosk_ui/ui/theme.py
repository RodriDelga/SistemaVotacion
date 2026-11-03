"""Tema visual: colores, tipografía, escalado según la resolución y botones."""
from __future__ import annotations

import customtkinter as ctk


class C:
    """Paleta. Contraste de texto >= 4.5:1 sobre sus fondos habituales."""
    BG = "#F4F7FB"
    SURFACE = "#FFFFFF"
    NAVY = "#0B1F3A"
    NAVY_HOVER = "#16345F"
    BLUE = "#1F4E9C"
    TEXT = "#0B1F3A"
    MUTED = "#4A5B75"
    BORDER = "#C9D3E3"
    SELECTED_BG = "#E8EFFA"
    OK = "#1B7F4B"
    ERR = "#B3261E"
    ERR_HOVER = "#8C1D18"
    WARN = "#B26A00"
    DISABLED_BG = "#D5DCE8"
    DISABLED_TEXT = "#5A6678"
    HEADER_SUB = "#B9C8E3"
    HOVER_LIGHT = "#E6ECF5"


class Theme:
    """Escala todo respecto a una altura de referencia de 1080 px."""

    def __init__(self, reference_height: int, family: str = "DejaVu Sans") -> None:
        self.scale = max(0.65, min(2.0, reference_height / 1080))
        self.family = family
        self._fonts: dict[tuple[int, bool], ctk.CTkFont] = {}

    def s(self, px: float) -> int:
        return max(1, int(round(px * self.scale)))

    def font(self, px: int, bold: bool = False) -> ctk.CTkFont:
        key = (px, bold)
        if key not in self._fonts:
            self._fonts[key] = ctk.CTkFont(
                family=self.family, size=self.s(px), weight="bold" if bold else "normal")
        return self._fonts[key]

    def tk_font(self, px: int, bold: bool = False) -> tuple:
        """Fuente como tupla (para Canvas); tamaño negativo = píxeles."""
        return (self.family, -self.s(px), "bold" if bold else "normal")

    def button(self, parent, text: str, command=None, kind: str = "primary",
               width: int | None = None, compact: bool = False, big: bool = False) -> ctk.CTkButton:
        """Botón grande. kind: 'primary' (azul marino) o 'secondary' (contorno)."""
        height = self.s(64 if compact else (104 if big else 84))
        font = self.font(26 if compact else (40 if big else 30), True)
        kw: dict = dict(text=text, command=command, height=height, font=font,
                        corner_radius=self.s(16), text_color_disabled=C.DISABLED_TEXT)
        if width:
            kw["width"] = width
        if kind == "secondary":
            kw.update(fg_color=C.SURFACE, hover_color=C.HOVER_LIGHT, text_color=C.NAVY,
                      border_width=self.s(3), border_color=C.NAVY)
        else:
            kw.update(fg_color=C.NAVY, hover_color=C.NAVY_HOVER, text_color="white", border_width=0)
        return ctk.CTkButton(parent, **kw)

    @staticmethod
    def set_enabled(btn: ctk.CTkButton, enabled: bool, kind: str = "primary") -> None:
        """CTkButton no cambia de fondo al deshabilitarse; se hace explícito."""
        if enabled:
            if kind == "secondary":
                btn.configure(state="normal", fg_color=C.SURFACE, border_color=C.NAVY)
            else:
                btn.configure(state="normal", fg_color=C.NAVY)
        else:
            btn.configure(state="disabled", fg_color=C.DISABLED_BG,
                          **({"border_color": C.BORDER} if kind == "secondary" else {}))
