"""
ui/components/toast.py — Notificaciones toast estilo Retrowave

Muestra notificaciones flotantes en la esquina inferior derecha
que se desvanecen automáticamente.

Uso:
    from ui.components.toast import show_toast
    show_toast(root, "Post publicado en LinkedIn ✓", kind="success")
    show_toast(root, "Error: token expirado", kind="error")
    show_toast(root, "Post programado para las 15:00", kind="info")
"""
from __future__ import annotations

import tkinter as tk
from typing import Literal

import customtkinter as ctk

from ui.theme import COLORS, FONTS, SPACING, RADIUS, blend_hex

ToastKind = Literal["success", "error", "warning", "info"]

_TOAST_CONFIG: dict[str, dict] = {
    "success": {"icon": "✓", "color": COLORS["success"],   "bg": "#0a2a1a"},
    "error":   {"icon": "✗", "color": COLORS["error"],     "bg": "#2a0a12"},
    "warning": {"icon": "⚠", "color": COLORS["neon_yellow"],"bg": "#2a2200"},
    "info":    {"icon": "◈", "color": COLORS["neon_cyan"],  "bg": "#0a1a2a"},
}

_active_toasts: list["_Toast"] = []
_MAX_TOASTS = 4


class _Toast(ctk.CTkToplevel):
    """Ventana toast individual."""

    HEIGHT    = 56
    WIDTH     = 360
    MARGIN    = 12
    DURATION  = 4000    # ms antes de empezar a desvanecerse
    FADE_STEP = 40      # ms entre pasos del fade
    FADE_DEC  = 0.08    # decremento de alpha por paso

    def __init__(self, master, message: str, kind: ToastKind = "info") -> None:
        super().__init__(master)

        cfg = _TOAST_CONFIG.get(kind, _TOAST_CONFIG["info"])

        # Estilo de ventana
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(fg_color=cfg["bg"])

        try:
            self.attributes("-alpha", 0.0)
        except Exception:
            pass

        # Borde de color
        border_frame = ctk.CTkFrame(
            self,
            fg_color=cfg["bg"],
            border_color=cfg["color"],
            border_width=1,
            corner_radius=RADIUS["card"],
        )
        border_frame.pack(fill="both", expand=True, padx=1, pady=1)

        # Icono
        ctk.CTkLabel(
            border_frame,
            text=cfg["icon"],
            font=("Segoe UI", 16, "bold"),
            text_color=cfg["color"],
            width=32,
        ).pack(side="left", padx=(SPACING["sm"], 0))

        # Mensaje
        ctk.CTkLabel(
            border_frame,
            text=message[:80],
            font=FONTS["small"],
            text_color=COLORS["text_primary"],
            anchor="w",
            wraplength=280,
            justify="left",
        ).pack(side="left", padx=SPACING["sm"], pady=SPACING["sm"], fill="x", expand=True)

        # Botón cerrar
        ctk.CTkButton(
            border_frame,
            text="×",
            width=24, height=24,
            font=("Segoe UI", 14),
            fg_color="transparent",
            hover_color=COLORS["bg_hover"],
            text_color=COLORS["text_secondary"],
            corner_radius=4,
            command=self._dismiss,
        ).pack(side="right", padx=SPACING["xs"])

        # Posicionar y mostrar
        self.update_idletasks()
        self._position()
        self._fade_in()
        self.after(self.DURATION, self._fade_out)

    def _position(self) -> None:
        """Posiciona el toast en la esquina inferior derecha, apilando los anteriores."""
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()

        # Calcular posición según cuántos toasts activos hay
        idx    = _active_toasts.index(self) if self in _active_toasts else 0
        offset = idx * (self.HEIGHT + self.MARGIN)

        x = sw - self.WIDTH - self.MARGIN
        y = sh - self.HEIGHT - self.MARGIN - offset - 40  # -40 para barra de tareas

        self.geometry(f"{self.WIDTH}x{self.HEIGHT}+{x}+{y}")

    def _fade_in(self, alpha: float = 0.0) -> None:
        alpha = min(1.0, alpha + self.FADE_DEC * 2)
        try:
            self.attributes("-alpha", alpha)
        except Exception:
            pass
        if alpha < 1.0:
            self.after(self.FADE_STEP, lambda: self._fade_in(alpha))

    def _fade_out(self, alpha: float = 1.0) -> None:
        alpha = max(0.0, alpha - self.FADE_DEC)
        try:
            self.attributes("-alpha", alpha)
        except Exception:
            pass
        if alpha > 0:
            self.after(self.FADE_STEP, lambda: self._fade_out(alpha))
        else:
            self._destroy()

    def _dismiss(self) -> None:
        self._fade_out()

    def _destroy(self) -> None:
        if self in _active_toasts:
            _active_toasts.remove(self)
        try:
            self.destroy()
        except Exception:
            pass
        # Reposicionar los toasts restantes
        for i, toast in enumerate(_active_toasts):
            toast._reposition(i)

    def _reposition(self, idx: int) -> None:
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x  = sw - self.WIDTH - self.MARGIN
        y  = sh - self.HEIGHT - self.MARGIN - idx * (self.HEIGHT + self.MARGIN) - 40
        try:
            self.geometry(f"{self.WIDTH}x{self.HEIGHT}+{x}+{y}")
        except Exception:
            pass


def show_toast(
    master,
    message: str,
    kind: ToastKind = "info",
) -> None:
    """
    Muestra una notificación toast flotante.

    Args:
        master:  Widget raíz CTk (normalmente la AppWindow).
        message: Texto de la notificación (máx ~80 chars visibles).
        kind:    "success" | "error" | "warning" | "info"

    Debe llamarse siempre desde el hilo principal (UI thread).
    Desde hilos background usar: master.after(0, lambda: show_toast(...))
    """
    # Eliminar el más antiguo si hay demasiados
    if len(_active_toasts) >= _MAX_TOASTS:
        oldest = _active_toasts[0]
        oldest._destroy()

    toast = _Toast(master, message, kind)
    _active_toasts.append(toast)
