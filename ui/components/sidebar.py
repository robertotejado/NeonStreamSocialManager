"""
ui/components/sidebar.py — Barra lateral de navegación

Muestra el logo, los ítems de menú y el estado de cuentas conectadas.
Emite un callback `on_navigate(view_name)` al hacer clic.
"""
from __future__ import annotations

from typing import Callable, Optional
import customtkinter as ctk

from ui.theme import COLORS, FONTS, RADIUS, SPACING, neon_button_style


# Ítems del menú: (nombre_vista, etiqueta, símbolo unicode)
NAV_ITEMS = [
    ("dashboard",  "Dashboard",     "⬡"),
    ("scheduler",  "Programador",   "◷"),
    ("ai_lab",     "AI Content Lab","✦"),
    ("analytics",  "Analytics",     "◈"),
    ("settings",   "Cuentas",       "◉"),
    ("config",     "Credenciales",  "⚙"),
]


class Sidebar(ctk.CTkFrame):
    """
    Panel lateral fijo con:
      • Logo ASCII/texto
      • Botones de navegación
      • Indicadores de cuentas conectadas (se actualiza desde fuera)
    """

    def __init__(
        self,
        master,
        on_navigate: Callable[[str], None],
        **kwargs,
    ):
        super().__init__(
            master,
            width=200,
            fg_color=COLORS["bg_panel"],
            border_color=COLORS["border"],
            border_width=1,
            corner_radius=0,
            **kwargs,
        )
        self.grid_propagate(False)

        self._on_navigate = on_navigate
        self._active_view: Optional[str] = None
        self._nav_buttons: dict[str, ctk.CTkButton] = {}

        self._build()

    def _build(self) -> None:
        self.grid_rowconfigure(len(NAV_ITEMS) + 2, weight=1)  # empuja footer abajo

        # ── Logo ──────────────────────────────────────────────────────────────
        logo_frame = ctk.CTkFrame(self, fg_color="transparent")
        logo_frame.grid(row=0, column=0, padx=SPACING["md"], pady=(SPACING["lg"], SPACING["sm"]), sticky="ew")

        ctk.CTkLabel(
            logo_frame,
            text="◈ NEON",
            font=("Consolas", 18, "bold"),
            text_color=COLORS["neon_purple"],
        ).pack(side="left")

        ctk.CTkLabel(
            logo_frame,
            text="STREAM",
            font=("Consolas", 18, "bold"),
            text_color=COLORS["neon_cyan"],
        ).pack(side="left")

        # Línea separadora
        sep = ctk.CTkFrame(self, height=1, fg_color=COLORS["border"])
        sep.grid(row=1, column=0, sticky="ew", padx=SPACING["sm"], pady=(0, SPACING["sm"]))

        # ── Botones de navegación ─────────────────────────────────────────────
        for i, (view_name, label, icon) in enumerate(NAV_ITEMS):
            btn = ctk.CTkButton(
                self,
                text=f"  {icon}  {label}",
                anchor="w",
                font=FONTS["body"],
                fg_color="transparent",
                hover_color=COLORS["bg_hover"],
                text_color=COLORS["text_secondary"],
                border_width=0,
                corner_radius=RADIUS["btn"],
                height=40,
                command=lambda v=view_name: self._navigate(v),
            )
            btn.grid(row=i + 2, column=0, padx=SPACING["sm"], pady=2, sticky="ew")
            self._nav_buttons[view_name] = btn

        # ── Footer: cuentas conectadas ────────────────────────────────────────
        self._accounts_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._accounts_frame.grid(
            row=len(NAV_ITEMS) + 3, column=0,
            padx=SPACING["sm"], pady=SPACING["md"], sticky="sew"
        )

        ctk.CTkLabel(
            self._accounts_frame,
            text="CUENTAS CONECTADAS",
            font=FONTS["badge"],
            text_color=COLORS["text_disabled"],
        ).pack(anchor="w", padx=SPACING["sm"])

        self._accounts_list = ctk.CTkFrame(self._accounts_frame, fg_color="transparent")
        self._accounts_list.pack(fill="x")

    def _navigate(self, view_name: str) -> None:
        """Cambia el estado visual del botón activo y emite el callback."""
        if self._active_view:
            prev_btn = self._nav_buttons.get(self._active_view)
            if prev_btn:
                prev_btn.configure(
                    fg_color="transparent",
                    text_color=COLORS["text_secondary"],
                    border_width=0,
                )

        btn = self._nav_buttons.get(view_name)
        if btn:
            btn.configure(
                fg_color=COLORS["bg_surface"],
                text_color=COLORS["neon_purple"],
                border_color=COLORS["neon_purple"],
                border_width=1,
            )

        self._active_view = view_name
        self._on_navigate(view_name)

    def set_active(self, view_name: str) -> None:
        """Activa un ítem del menú desde fuera (por ejemplo al iniciar la app)."""
        self._navigate(view_name)

    def update_accounts(self, accounts: list[dict]) -> None:
        """
        Actualiza los indicadores de cuentas conectadas en el footer.

        Args:
            accounts: Lista de dicts con keys 'platform', 'display_name', 'is_active'.
        """
        for widget in self._accounts_list.winfo_children():
            widget.destroy()

        PLATFORM_ICONS = {
            "linkedin":  "in",
            "x_twitter": "𝕏",
            "instagram": "◉",
            "facebook":  "f",
            "tiktok":    "♪",
        }

        for acc in accounts[:5]:  # máx 5 en sidebar
            platform = acc.get("platform", "")
            icon = PLATFORM_ICONS.get(platform, "●")
            name = acc.get("display_name") or acc.get("username") or platform
            color = COLORS.get(platform, COLORS["neon_purple"])

            row = ctk.CTkFrame(self._accounts_list, fg_color="transparent")
            row.pack(fill="x", padx=SPACING["sm"], pady=2)

            # Dot de estado
            dot_color = COLORS["success"] if acc.get("is_active") else COLORS["error"]
            ctk.CTkLabel(row, text="●", font=FONTS["badge"], text_color=dot_color, width=12).pack(side="left")

            ctk.CTkLabel(
                row,
                text=f"{icon} {name[:16]}",
                font=FONTS["small"],
                text_color=COLORS["text_secondary"],
                anchor="w",
            ).pack(side="left", padx=(4, 0))

        if not accounts:
            ctk.CTkLabel(
                self._accounts_list,
                text="Sin cuentas conectadas",
                font=FONTS["small"],
                text_color=COLORS["text_disabled"],
            ).pack(anchor="w", padx=SPACING["sm"])
