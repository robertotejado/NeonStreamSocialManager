"""
ui/components/status_bar.py — Barra de estado inferior

Muestra en tiempo real:
  • Estado del scheduler (jobs pendientes)
  • Estado de la conexión a DB
  • Estado de Gemini (API key configurada o no)
  • Hora UTC actual
  • Indicador de actividad (spinner ASCII)

Se actualiza cada 5 segundos sin bloquear la UI (CTk.after).
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Optional

import customtkinter as ctk

from ui.theme import COLORS, FONTS, SPACING


_SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


class StatusBar(ctk.CTkFrame):
    """
    Barra horizontal fija en la parte inferior de la ventana.

    Segmentos (izq → der):
      [spinner + actividad]  [scheduler]  [DB]  [Gemini]  [hora UTC]
    """

    REFRESH_MS = 5_000   # actualizar cada 5 s

    def __init__(self, master, **kwargs) -> None:
        super().__init__(
            master,
            height=28,
            fg_color=COLORS["bg_panel"],
            border_color=COLORS["border"],
            corner_radius=0,
            **kwargs,
        )
        self.grid_propagate(False)
        self._spinner_idx = 0
        self._activity_msg = ""
        self._build()
        self._schedule_refresh()

    def _build(self) -> None:
        self.grid_columnconfigure(1, weight=1)  # espacio central elástico

        # Spinner + mensaje de actividad (izquierda)
        self._spinner_label = ctk.CTkLabel(
            self, text="",
            font=("Consolas", 11), text_color=COLORS["text_disabled"],
        )
        self._spinner_label.grid(row=0, column=0, padx=(SPACING["sm"], 0))

        self._activity_label = ctk.CTkLabel(
            self, text="",
            font=FONTS["small"], text_color=COLORS["text_secondary"],
        )
        self._activity_label.grid(row=0, column=1, sticky="w", padx=SPACING["xs"])

        # Separadores y pills de estado (derecha)
        right_frame = ctk.CTkFrame(self, fg_color="transparent")
        right_frame.grid(row=0, column=2, sticky="e", padx=SPACING["sm"])

        self._scheduler_pill = self._make_pill(right_frame, "◷ Scheduler")
        self._scheduler_pill.pack(side="left", padx=SPACING["xs"])

        self._db_pill = self._make_pill(right_frame, "◉ DB")
        self._db_pill.pack(side="left", padx=SPACING["xs"])

        self._gemini_pill = self._make_pill(right_frame, "✦ Gemini")
        self._gemini_pill.pack(side="left", padx=SPACING["xs"])

        # Separador visual
        ctk.CTkLabel(right_frame, text="│", font=FONTS["small"],
                     text_color=COLORS["border"]).pack(side="left", padx=SPACING["xs"])

        # Reloj UTC
        self._clock_label = ctk.CTkLabel(
            right_frame, text="--:-- UTC",
            font=("Consolas", 11), text_color=COLORS["text_secondary"],
        )
        self._clock_label.pack(side="left", padx=(SPACING["xs"], SPACING["sm"]))

    @staticmethod
    def _make_pill(parent, text: str) -> ctk.CTkLabel:
        return ctk.CTkLabel(
            parent, text=text,
            font=FONTS["badge"],
            text_color=COLORS["text_disabled"],
            fg_color=COLORS["bg_surface"],
            corner_radius=10,
            padx=6, pady=1,
        )

    # ── Refresh ───────────────────────────────────────────────────────────────

    def _schedule_refresh(self) -> None:
        self._do_refresh()
        self.after(self.REFRESH_MS, self._schedule_refresh)

    def _do_refresh(self) -> None:
        """Lanza el chequeo en un hilo daemon para no bloquear la UI."""
        threading.Thread(target=self._collect_status, daemon=True).start()
        self._tick_spinner()
        self._update_clock()

    def _collect_status(self) -> None:
        scheduler_text, scheduler_color = self._check_scheduler()
        db_text, db_color               = self._check_db()
        gemini_text, gemini_color       = self._check_gemini()

        self.after(0, lambda: self._apply_status(
            scheduler_text, scheduler_color,
            db_text, db_color,
            gemini_text, gemini_color,
        ))

    def _apply_status(self,
                      sched_t, sched_c,
                      db_t, db_c,
                      gem_t, gem_c) -> None:
        self._scheduler_pill.configure(text=sched_t, text_color=sched_c)
        self._db_pill.configure(text=db_t, text_color=db_c)
        self._gemini_pill.configure(text=gem_t, text_color=gem_c)

    # ── Checks individuales ───────────────────────────────────────────────────

    @staticmethod
    def _check_scheduler() -> tuple[str, str]:
        try:
            from services.scheduler import get_scheduler, list_pending_jobs
            sched = get_scheduler()
            if not sched.running:
                return "◷ Scheduler OFF", COLORS["error"]
            n = len(list_pending_jobs())
            color = COLORS["neon_cyan"] if n > 0 else COLORS["success"]
            return f"◷ {n} job{'s' if n != 1 else ''}", color
        except Exception:
            return "◷ Scheduler —", COLORS["text_disabled"]

    @staticmethod
    def _check_db() -> tuple[str, str]:
        try:
            from models.database import get_engine
            engine = get_engine()
            with engine.connect() as conn:
                conn.execute(__import__("sqlalchemy").text("SELECT 1"))
            return "◉ DB OK", COLORS["success"]
        except Exception:
            return "◉ DB ✗", COLORS["error"]

    @staticmethod
    def _check_gemini() -> tuple[str, str]:
        try:
            from services.gemini_ai import is_gemini_available
            if is_gemini_available():
                return "✦ Gemini ✓", COLORS["neon_purple"]
            return "✦ Gemini —", COLORS["text_disabled"]
        except Exception:
            return "✦ Gemini —", COLORS["text_disabled"]

    # ── Helpers UI ────────────────────────────────────────────────────────────

    def _tick_spinner(self) -> None:
        if self._activity_msg:
            self._spinner_label.configure(
                text=_SPINNER[self._spinner_idx % len(_SPINNER)],
                text_color=COLORS["neon_cyan"],
            )
            self._spinner_idx += 1
        else:
            self._spinner_label.configure(text="")

    def _update_clock(self) -> None:
        now = datetime.now(timezone.utc).strftime("%H:%M UTC")
        self._clock_label.configure(text=now)

    # ── API pública ───────────────────────────────────────────────────────────

    def set_activity(self, message: str) -> None:
        """
        Muestra un mensaje de actividad con spinner animado.
        Llamar con message="" para limpiar.
        """
        self._activity_msg = message
        self._activity_label.configure(text=message)
        if not message:
            self._spinner_label.configure(text="")
