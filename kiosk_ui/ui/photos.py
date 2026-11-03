"""Fotografías de candidatos.

Si el candidato trae `photo_path` y el archivo se puede abrir, se usa esa foto.
Si no, se dibuja un avatar con sus iniciales (datos de ejemplo, sin archivos
binarios en el repositorio). Requiere Pillow.
"""
from __future__ import annotations

import zlib

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageFont, ImageOps

from kiosk_ui.core.models import Candidate

_PALETTE = ("#1F4E9C", "#2A6F97", "#3A5A9B", "#2F7F86", "#44639A")
_cache: dict[tuple, ctk.CTkImage] = {}


def initials(name: str) -> str:
    parts = [p for p in name.split() if p]
    if not parts:
        return "?"
    return (parts[0][0] + parts[1][0]).upper() if len(parts) > 1 else parts[0][:2].upper()


def _font(px: int):
    for name in ("DejaVuSans-Bold.ttf", "DejaVuSans.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            continue
    return ImageFont.load_default()


def _avatar(candidate: Candidate, size: int) -> Image.Image:
    color = _PALETTE[zlib.crc32(candidate.id.encode()) % len(_PALETTE)]
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=size // 8, fill=color)
    text = initials(candidate.name)
    font = _font(size // 3)
    box = draw.textbbox((0, 0), text, font=font)
    x = (size - (box[2] - box[0])) / 2 - box[0]
    y = (size - (box[3] - box[1])) / 2 - box[1]
    draw.text((x, y), text, font=font, fill="white")
    return img


def candidate_image(candidate: Candidate, px: int) -> ctk.CTkImage:
    """Imagen cuadrada de `px` píxeles lógicos (se dibuja al doble para nitidez)."""
    key = (candidate.id, candidate.photo_path, px)
    if key in _cache:
        return _cache[key]
    big = px * 2
    img = None
    if candidate.photo_path:
        try:
            img = ImageOps.fit(Image.open(candidate.photo_path).convert("RGB"), (big, big))
        except OSError:
            img = None
    if img is None:
        img = _avatar(candidate, big)
    _cache[key] = ctk.CTkImage(light_image=img, size=(px, px))
    return _cache[key]
