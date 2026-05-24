"""
ui/assets/generate_icon.py — Genera el icono de la aplicación

Crea neonstream.ico usando solo PIL (sin assets externos).
El icono dibuja la "N" estilizada con gradiente neón violeta/cian.

Uso:
    python ui/assets/generate_icon.py
    → genera ui/assets/neonstream.ico  (multi-resolución: 16,32,48,64,128,256 px)

Se llama automáticamente desde build.bat si el .ico no existe.
"""
from __future__ import annotations

import math
import os
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent
ICO_PATH   = OUTPUT_DIR / "neonstream.ico"
PNG_PATH   = OUTPUT_DIR / "neonstream_256.png"


def _draw_icon(size: int):
    """Dibuja el icono NeonStream en un lienzo de `size` x `size`."""
    from PIL import Image, ImageDraw, ImageFilter

    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Fondo redondeado oscuro
    pad = max(2, size // 16)
    r   = size // 4
    draw.rounded_rectangle([pad, pad, size - pad, size - pad],
                            radius=r, fill=(13, 13, 26, 255))

    # Borde neón violeta
    bw = max(1, size // 32)
    draw.rounded_rectangle([pad, pad, size - pad, size - pad],
                            radius=r, outline=(180, 79, 255, 220), width=bw)

    # Letra "N" con trazo neón
    m   = size // 5          # margen interior
    lw  = max(2, size // 12) # grosor de línea
    x0, y0 = m, m
    x1, y1 = size - m, size - m

    # Trazo violeta: barra izquierda, diagonal y barra derecha
    neon_purple = (180, 79, 255, 255)
    neon_cyan   = (0, 245, 233, 255)

    # Barra izquierda (violeta)
    draw.line([(x0, y0), (x0, y1)], fill=neon_purple, width=lw)
    # Diagonal (gradiente visual: cyan en el centro)
    mid_x = (x0 + x1) // 2
    mid_y = (y0 + y1) // 2
    draw.line([(x0, y0), (mid_x, mid_y)], fill=neon_purple, width=lw)
    draw.line([(mid_x, mid_y), (x1, y1)], fill=neon_cyan,   width=lw)
    # Barra derecha (cyan)
    draw.line([(x1, y0), (x1, y1)], fill=neon_cyan, width=lw)

    # Glow suave (blur + composite)
    glow = img.copy().filter(ImageFilter.GaussianBlur(radius=max(1, size // 20)))
    result = Image.alpha_composite(glow, img)

    return result


def generate_icon() -> None:
    """Genera el .ico multi-resolución y el PNG de 256px."""
    try:
        from PIL import Image
    except ImportError:
        print("Pillow no instalado. Ejecuta: pip install pillow")
        return

    sizes = [16, 32, 48, 64, 128, 256]
    frames = [_draw_icon(s) for s in sizes]

    # Guardar PNG 256 (para Linux/Mac)
    frames[-1].save(str(PNG_PATH))
    print(f"  ✓ PNG guardado: {PNG_PATH}")

    # Guardar ICO multi-resolución (para Windows)
    frames[0].save(
        str(ICO_PATH),
        format="ICO",
        append_images=frames[1:],
        sizes=[(s, s) for s in sizes],
    )
    print(f"  ✓ ICO guardado: {ICO_PATH}")


if __name__ == "__main__":
    print("Generando icono NeonStream…")
    generate_icon()
    print("Listo.")
