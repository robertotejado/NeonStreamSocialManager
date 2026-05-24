"""
ui/app_window.py — Ventana principal de NeonStream (CustomTkinter)

Arquitectura:
  • CTk() en el hilo principal — es el event loop de la UI.
  • OAuthBridge (uvicorn daemon) arranca en un hilo background.
  • APScheduler arranca en otro hilo background.
  • Las vistas se cargan lazy (solo cuando se navegan por primera vez).

Layout:
  ┌────────────┬──────────────────────────────────────────┐
  │            │                                          │
  │  Sidebar   │          Content Area                    │
  │  (200px)   │  (cambia según la vista activa)          │
  │            │                                          │
  └────────────┴──────────────────────────────────────────┘
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

import customtkinter as ctk

from ui.theme import COLORS, FONTS, SPACING, apply_theme
from ui.components.sidebar import Sidebar
from ui.components.status_bar import StatusBar
from ui.components.toast import show_toast

logger = logging.getLogger(__name__)


class AppWindow(ctk.CTk):
    """
    Ventana raíz de NeonStream. Gestiona:
      - El layout de sidebar + contenido
      - La navegación entre vistas (lazy loading)
      - El ciclo de vida de los servicios background
    """

    MIN_WIDTH  = 1100
    MIN_HEIGHT = 700

    def __init__(self) -> None:
        apply_theme()
        super().__init__()

        self.title("NeonStream Social Manager")
        self.geometry(f"{self.MIN_WIDTH}x{self.MIN_HEIGHT}")
        self.minsize(self.MIN_WIDTH, self.MIN_HEIGHT)
        self.configure(fg_color=COLORS["bg_deep"])

        # Icono de la ventana (se crea desde assets en producción)
        # self.iconbitmap("ui/assets/icon.ico")

        self._views: dict[str, ctk.CTkFrame] = {}
        self._current_view: Optional[str] = None
        self._accounts: list[dict] = []

        self._build_layout()
        self._start_background_services()

        # Navegar a dashboard al arrancar
        self.after(100, lambda: self._sidebar.set_active("dashboard"))

        # Protocolo de cierre limpio
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Escuchar evento de envío al scheduler desde AI Lab
        self.bind("<<SendToScheduler>>", self._on_send_to_scheduler)

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_layout(self) -> None:
        # Fila 0: sidebar + contenido (elástico)
        # Fila 1: status bar (fija, 28px)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)

        # Sidebar
        self._sidebar = Sidebar(self, on_navigate=self._navigate)
        self._sidebar.grid(row=0, column=0, rowspan=2, sticky="nsew")

        # Contenedor del área de contenido
        self._content_area = ctk.CTkFrame(self, fg_color=COLORS["bg_deep"])
        self._content_area.grid(row=0, column=1, sticky="nsew")
        self._content_area.grid_columnconfigure(0, weight=1)
        self._content_area.grid_rowconfigure(0, weight=1)

        # Status bar inferior
        self._status_bar = StatusBar(self)
        self._status_bar.grid(row=1, column=1, sticky="ew")

    # ── Navegación ────────────────────────────────────────────────────────────

    def _navigate(self, view_name: str) -> None:
        """Muestra la vista solicitada, creándola si es la primera vez."""
        if self._current_view == view_name:
            return

        # Ocultar vista actual
        if self._current_view and self._current_view in self._views:
            self._views[self._current_view].grid_remove()

        # Crear vista si no existe (lazy loading)
        if view_name not in self._views:
            view = self._create_view(view_name)
            if view is None:
                return
            view.grid(row=0, column=0, sticky="nsew", in_=self._content_area)
            self._views[view_name] = view
        else:
            self._views[view_name].grid()

        # Notificar a la vista que se está mostrando (si tiene hook)
        view = self._views[view_name]
        if hasattr(view, "on_show"):
            view.on_show()

        self._current_view = view_name
        logger.debug("Navegando a vista: %s", view_name)

    def _create_view(self, view_name: str) -> Optional[ctk.CTkFrame]:
        """Instancia la vista correspondiente al nombre."""
        parent = self._content_area

        if view_name == "dashboard":
            from ui.views.dashboard_view import DashboardView
            return DashboardView(parent)

        elif view_name == "scheduler":
            from ui.views.scheduler_view import SchedulerView
            return SchedulerView(parent)

        elif view_name == "ai_lab":
            from ui.views.ai_lab_view import AILabView
            return AILabView(parent)

        elif view_name == "analytics":
            from ui.views.analytics_view import AnalyticsView
            return AnalyticsView(parent)

        elif view_name == "settings":
            from ui.views.settings_view import SettingsView
            return SettingsView(
                parent,
                on_accounts_changed=self._on_accounts_changed,
            )

        elif view_name == "config":
            from ui.views.config_view import ConfigView
            return ConfigView(parent)

        logger.warning("Vista desconocida: %s", view_name)
        return None

    # ── Servicios background ──────────────────────────────────────────────────

    def _start_background_services(self) -> None:
        """Arranca APScheduler y el OAuthBridge en hilos daemon."""

        def _start():
            # Init DB
            from models.database import init_db
            init_db()

            # APScheduler
            try:
                from services.scheduler import get_scheduler, register_ui_window
                get_scheduler().start()
                register_ui_window(self)   # para toasts desde jobs
                logger.info("APScheduler iniciado.")
            except Exception as exc:
                logger.error("Error iniciando APScheduler: %s", exc)

            # OAuthBridge (uvicorn daemon)
            try:
                from services.oauth_bridge import get_oauth_bridge
                bridge = get_oauth_bridge()
                bridge.start_server()
                logger.info("OAuthBridge iniciado en localhost:8000")
            except Exception as exc:
                logger.error("Error iniciando OAuthBridge: %s", exc)

        threading.Thread(target=_start, name="services-init", daemon=True).start()

    # ── Callbacks inter-vista ─────────────────────────────────────────────────

    def _on_accounts_changed(self, accounts: list[dict]) -> None:
        """Actualiza el sidebar cuando cambian las cuentas conectadas."""
        self._accounts = accounts
        self._sidebar.update_accounts(accounts)

    def _on_send_to_scheduler(self, event) -> None:
        """Recibe contenido del AI Lab y lo envía al Scheduler."""
        content = event.data if hasattr(event, "data") else ""
        self._navigate("scheduler")
        scheduler_view = self._views.get("scheduler")
        if scheduler_view and hasattr(scheduler_view, "prefill_content"):
            scheduler_view.prefill_content(content)

    def notify(self, message: str, kind: str = "info") -> None:
        """
        Muestra un toast desde cualquier módulo.
        Uso: app.notify("Post publicado ✓", kind="success")
        Desde hilos: self.after(0, lambda: app.notify(...))
        """
        try:
            show_toast(self, message, kind=kind)
        except Exception:
            pass

    # ── Cierre limpio ─────────────────────────────────────────────────────────

    def _on_close(self) -> None:
        """Apaga los servicios background antes de cerrar la ventana."""
        logger.info("Cerrando NeonStream…")
        try:
            from services.scheduler import get_scheduler
            get_scheduler().shutdown(wait=False)
        except Exception:
            pass
        self.destroy()


# ══════════════════════════════════════════════════════════════════════════════
#  Vistas stub para completar la navegación (Dashboard, Scheduler, Analytics)
#  Se sustituyen por implementaciones completas en las siguientes fases.
# ══════════════════════════════════════════════════════════════════════════════

def _stub_view(parent, title: str, subtitle: str, color: str) -> ctk.CTkFrame:
    """Genera una vista placeholder con estética Retrowave."""
    frame = ctk.CTkFrame(parent, fg_color=COLORS["bg_deep"])
    frame.grid_columnconfigure(0, weight=1)
    frame.grid_rowconfigure(0, weight=1)

    center = ctk.CTkFrame(frame, fg_color="transparent")
    center.place(relx=0.5, rely=0.5, anchor="center")

    ctk.CTkLabel(center, text=title, font=("Consolas", 48, "bold"),
                 text_color=color).pack()
    ctk.CTkLabel(center, text=subtitle, font=FONTS["heading"],
                 text_color=COLORS["text_secondary"]).pack(pady=SPACING["sm"])
    ctk.CTkLabel(center, text="— Próximamente —", font=FONTS["small"],
                 text_color=COLORS["text_disabled"]).pack()
    return frame
