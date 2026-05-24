"""
ui/theme.py — Paleta Retrowave/Outrun para CustomTkinter

Paleta Outrun:
  Fondo profundo  #0d0d1a  — negro azulado
  Panel           #12122a  — azul noche
  Surface         #1a1a3e  — azul índigo oscuro
  Borde           #2a2a5a  — índigo medio
  Neón violeta    #b44fff  — púrpura brillante
  Neón cian       #00f5e9  — cian eléctrico
  Neón rosa       #ff2d78  — magenta/rosa
  Neón amarillo   #ffd319  — amarillo ámbar
  Texto primario  #e8e8ff  — lavanda blanco
  Texto secundario #7a7ab8 — violeta apagado

Uso:
    from ui.theme import apply_theme, COLORS, FONTS
    apply_theme()  # llamar ANTES de crear la ventana CTk
"""
from __future__ import annotations

import customtkinter as ctk
from typing import Final

# ══════════════════════════════════════════════════════════════════════════════
#  Paleta de colores
# ══════════════════════════════════════════════════════════════════════════════

COLORS: Final[dict[str, str]] = {
    # Fondos
    "bg_deep":       "#0d0d1a",
    "bg_panel":      "#12122a",
    "bg_surface":    "#1a1a3e",
    "bg_input":      "#0f0f25",
    "bg_hover":      "#22225a",

    # Bordes
    "border":        "#2a2a5a",
    "border_focus":  "#b44fff",
    "border_active": "#00f5e9",

    # Neones principales
    "neon_purple":   "#b44fff",
    "neon_cyan":     "#00f5e9",
    "neon_pink":     "#ff2d78",
    "neon_yellow":   "#ffd319",

    # Neones suaves (para texto/iconos)
    "neon_purple_dim": "#7a35cc",
    "neon_cyan_dim":   "#00b8ad",
    "neon_pink_dim":   "#cc2060",

    # Texto
    "text_primary":    "#e8e8ff",
    "text_secondary":  "#7a7ab8",
    "text_disabled":   "#3a3a6a",
    "text_on_neon":    "#0d0d1a",

    # Estados semánticos
    "success":  "#00ff9f",
    "warning":  "#ffd319",
    "error":    "#ff2d78",
    "info":     "#00f5e9",

    # Plataformas (badges)
    "linkedin":  "#0a66c2",
    "x_twitter": "#1da1f2",
    "instagram": "#e1306c",
    "facebook":  "#1877f2",
    "tiktok":    "#ff0050",
    "telegram":  "#229ed9",
    "gemini":    "#4285f4",
}

# ══════════════════════════════════════════════════════════════════════════════
#  Tipografía
# ══════════════════════════════════════════════════════════════════════════════

FONTS: Final[dict[str, tuple]] = {
    "title":      ("Segoe UI", 22, "bold"),
    "heading":    ("Segoe UI", 16, "bold"),
    "subheading": ("Segoe UI", 13, "bold"),
    "body":       ("Segoe UI", 12, "normal"),
    "small":      ("Segoe UI", 11, "normal"),
    "mono":       ("Consolas", 11, "normal"),
    "mono_bold":  ("Consolas", 12, "bold"),
    "badge":      ("Segoe UI", 10, "bold"),
}

# ══════════════════════════════════════════════════════════════════════════════
#  Dimensiones y radios
# ══════════════════════════════════════════════════════════════════════════════

RADIUS: Final[dict[str, int]] = {
    "btn":    8,
    "card":   12,
    "input":  8,
    "badge":  20,   # pill
    "panel":  16,
}

SPACING: Final[dict[str, int]] = {
    "xs": 4,
    "sm": 8,
    "md": 16,
    "lg": 24,
    "xl": 32,
}

# ══════════════════════════════════════════════════════════════════════════════
#  Configuración global de CustomTkinter
# ══════════════════════════════════════════════════════════════════════════════

def apply_theme() -> None:
    """
    Aplica el tema Retrowave a CustomTkinter.
    Debe llamarse ANTES de instanciar CTk().
    """
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")

    # Sobreescribir el tema con nuestra paleta Outrun
    # CTk usa (light_color, dark_color) en tuplas para muchos widgets
    _patch_ctk_theme()


def _patch_ctk_theme() -> None:
    """
    Parchea los colores del tema CTk interno.
    Accede a ThemeManager para modificar la paleta en runtime.
    """
    try:
        from customtkinter.windows.widgets.theme import ThemeManager
        tm = ThemeManager.theme

        c = COLORS

        # CTkFrame
        tm["CTkFrame"]["fg_color"]          = [c["bg_panel"],   c["bg_panel"]]
        tm["CTkFrame"]["top_fg_color"]       = [c["bg_surface"], c["bg_surface"]]
        tm["CTkFrame"]["border_color"]       = [c["border"],     c["border"]]

        # CTkButton — primario (neón violeta)
        tm["CTkButton"]["fg_color"]          = [c["neon_purple_dim"], c["neon_purple_dim"]]
        tm["CTkButton"]["hover_color"]       = [c["neon_purple"],     c["neon_purple"]]
        tm["CTkButton"]["border_color"]      = [c["neon_purple"],     c["neon_purple"]]
        tm["CTkButton"]["text_color"]        = [c["text_primary"],    c["text_primary"]]
        tm["CTkButton"]["text_color_disabled"] = [c["text_disabled"], c["text_disabled"]]

        # CTkEntry
        tm["CTkEntry"]["fg_color"]           = [c["bg_input"],   c["bg_input"]]
        tm["CTkEntry"]["border_color"]       = [c["border"],     c["border_focus"]]
        tm["CTkEntry"]["text_color"]         = [c["text_primary"], c["text_primary"]]
        tm["CTkEntry"]["placeholder_text_color"] = [c["text_secondary"], c["text_secondary"]]

        # CTkTextbox
        tm["CTkTextbox"]["fg_color"]         = [c["bg_input"],   c["bg_input"]]
        tm["CTkTextbox"]["border_color"]     = [c["border"],     c["border"]]
        tm["CTkTextbox"]["text_color"]       = [c["text_primary"], c["text_primary"]]
        tm["CTkTextbox"]["scrollbar_button_color"] = [c["border"], c["neon_purple_dim"]]

        # CTkLabel
        tm["CTkLabel"]["text_color"]         = [c["text_primary"], c["text_primary"]]

        # CTkSegmentedButton
        tm["CTkSegmentedButton"]["fg_color"]           = [c["bg_surface"],      c["bg_surface"]]
        tm["CTkSegmentedButton"]["selected_color"]     = [c["neon_purple_dim"], c["neon_purple_dim"]]
        tm["CTkSegmentedButton"]["selected_hover_color"] = [c["neon_purple"],   c["neon_purple"]]
        tm["CTkSegmentedButton"]["unselected_color"]   = [c["bg_surface"],      c["bg_surface"]]
        tm["CTkSegmentedButton"]["unselected_hover_color"] = [c["bg_hover"],    c["bg_hover"]]
        tm["CTkSegmentedButton"]["text_color"]         = [c["text_secondary"],  c["text_secondary"]]
        tm["CTkSegmentedButton"]["text_color_disabled"] = [c["text_disabled"],  c["text_disabled"]]

        # CTkProgressBar
        tm["CTkProgressBar"]["fg_color"]         = [c["bg_surface"],      c["bg_surface"]]
        tm["CTkProgressBar"]["progress_color"]   = [c["neon_cyan"],        c["neon_cyan"]]
        tm["CTkProgressBar"]["border_color"]     = [c["border"],           c["border"]]

        # CTkSwitch
        tm["CTkSwitch"]["progress_color"]    = [c["neon_cyan"], c["neon_cyan"]]
        tm["CTkSwitch"]["button_color"]      = [c["text_primary"], c["text_primary"]]
        tm["CTkSwitch"]["fg_color"]          = [c["bg_surface"], c["bg_surface"]]

        # CTkComboBox / CTkOptionMenu
        tm["CTkComboBox"]["fg_color"]        = [c["bg_input"],   c["bg_input"]]
        tm["CTkComboBox"]["border_color"]    = [c["border"],     c["border_focus"]]
        tm["CTkComboBox"]["button_color"]    = [c["neon_purple_dim"], c["neon_purple_dim"]]
        tm["CTkComboBox"]["button_hover_color"] = [c["neon_purple"], c["neon_purple"]]
        tm["CTkComboBox"]["text_color"]      = [c["text_primary"], c["text_primary"]]

        # CTkScrollbar
        tm["CTkScrollbar"]["fg_color"]       = ["gray10", "gray10"]
        tm["CTkScrollbar"]["button_color"]   = [c["border"],   c["neon_purple_dim"]]
        tm["CTkScrollbar"]["button_hover_color"] = [c["neon_purple"], c["neon_purple"]]

    except Exception:
        # Si la versión de CTk cambia la estructura interna, no rompemos la app
        pass


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers de estilo para widgets manuales (Canvas, tk.Label…)
# ══════════════════════════════════════════════════════════════════════════════


def blend_hex(fg: str, bg: str = "#1a1a3e", alpha: float = 0.20) -> str:
    """
    Mezcla fg sobre bg con el alpha dado y devuelve un color #rrggbb válido.
    Tkinter no soporta colores de 8 dígitos (#rrggbbaa), así que calculamos
    el color resultante manualmente.

    Args:
        fg:    Color de primer plano en formato #rrggbb o #rgb.
        bg:    Color de fondo (por defecto el bg_surface del tema).
        alpha: Opacidad de fg (0.0 = totalmente transparente, 1.0 = opaco).
    """
    def parse(c: str):
        c = c.lstrip("#")
        if len(c) == 3:
            c = c[0]*2 + c[1]*2 + c[2]*2
        return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)

    fr, fg_, fb = parse(fg)
    br, bg_, bb = parse(bg)
    rr = round(br + alpha * (fr - br))
    rg = round(bg_ + alpha * (fg_ - bg_))
    rb = round(bb + alpha * (fb - bb))
    return f"#{rr:02x}{rg:02x}{rb:02x}"

def neon_button_style(neon_color: str = "neon_purple", corner_radius: int | None = None) -> dict:
    """
    Kwargs para un CTkButton con borde neón.
    corner_radius se incluye solo si se pasa explícitamente,
    para evitar 'multiple values' cuando el caller también lo especifica.
    """
    c = COLORS
    style = {
        "fg_color":     c["bg_surface"],
        "hover_color":  blend_hex(c[neon_color], bg=c["bg_surface"], alpha=0.20),
        "border_color": c[neon_color],
        "border_width": 1,
        "text_color":   c[neon_color],
    }
    if corner_radius is not None:
        style["corner_radius"] = corner_radius
    return style


def danger_button_style(corner_radius: int | None = None) -> dict:
    """CTkButton estilo destructivo (rojo/rosa neón)."""
    c = COLORS
    style = {
        "fg_color":    c["neon_pink_dim"],
        "hover_color": c["neon_pink"],
        "text_color":  c["text_primary"],
    }
    if corner_radius is not None:
        style["corner_radius"] = corner_radius
    return style


def card_frame_style(corner_radius: int | None = None) -> dict:
    """Kwargs para un CTkFrame que actúe como tarjeta."""
    style = {
        "fg_color":     COLORS["bg_surface"],
        "border_color": COLORS["border"],
        "border_width": 1,
    }
    if corner_radius is not None:
        style["corner_radius"] = corner_radius
    return style


def platform_color(platform: str) -> str:
    """Devuelve el color de marca de una plataforma."""
    return COLORS.get(platform.lower(), COLORS["neon_purple"])
