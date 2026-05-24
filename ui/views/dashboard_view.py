"""
ui/views/dashboard_view.py — Dashboard principal

Muestra en tiempo real:
  • Stat cards: posts publicados hoy / programados / fallidos / cuentas conectadas
  • Feed de actividad reciente (últimos 20 posts con estado)
  • Panel lateral con cuentas conectadas y estado de tokens
  
Datos: se cargan en hilo background y se refrescan cada 30 s o al llamar on_show().
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone, timedelta
from typing import Optional

import customtkinter as ctk

from ui.theme import (
    COLORS, FONTS, RADIUS, SPACING,
    card_frame_style, neon_button_style, blend_hex,
)

logger = logging.getLogger(__name__)

STATUS_COLORS = {
    "draft":      COLORS["text_disabled"],
    "scheduled":  COLORS["neon_cyan"],
    "publishing": COLORS["neon_yellow"],
    "published":  COLORS["success"],
    "failed":     COLORS["error"],
    "cancelled":  COLORS["text_disabled"],
}
STATUS_ICONS = {
    "draft": "○", "scheduled": "◷", "publishing": "⟳",
    "published": "✓", "failed": "✗", "cancelled": "⊘",
}
PLATFORM_ICONS = {
    "linkedin": "in", "x_twitter": "𝕏",
    "instagram": "◉", "facebook": "f", "tiktok": "♪",
}


class DashboardView(ctk.CTkFrame):
    """Dashboard principal con stats en vivo y feed de actividad."""

    REFRESH_INTERVAL_MS = 30_000  # 30 s

    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color=COLORS["bg_deep"], **kwargs)
        self._refresh_job: Optional[str] = None
        self._build()

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=3)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # ── Header ────────────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.grid(row=0, column=0, columnspan=2, sticky="ew",
                 padx=SPACING["lg"], pady=(SPACING["lg"], SPACING["sm"]))

        ctk.CTkLabel(
            hdr, text="⬡  Dashboard",
            font=FONTS["title"], text_color=COLORS["neon_cyan"],
        ).pack(side="left")

        self._last_refresh_lbl = ctk.CTkLabel(
            hdr, text="",
            font=FONTS["small"], text_color=COLORS["text_disabled"],
        )
        self._last_refresh_lbl.pack(side="right")

        ctk.CTkButton(
            hdr, text="↺ Actualizar", height=28, width=110,
            font=FONTS["small"],
            **neon_button_style("neon_cyan", corner_radius=RADIUS["btn"]),
            command=self._refresh,
        ).pack(side="right", padx=SPACING["sm"])

        # ── Panel izquierdo: stats + feed ─────────────────────────────────────
        left = ctk.CTkFrame(self, fg_color="transparent")
        left.grid(row=1, column=0, sticky="nsew",
                  padx=(SPACING["lg"], SPACING["sm"]), pady=(0, SPACING["lg"]))
        left.grid_columnconfigure((0,1,2,3), weight=1)
        left.grid_rowconfigure(1, weight=1)

        # Stat cards
        self._stat_labels: dict[str, ctk.CTkLabel] = {}
        stats_def = [
            ("published_today", "Publicados hoy",    "✓", COLORS["success"]),
            ("scheduled",       "Programados",        "◷", COLORS["neon_cyan"]),
            ("failed",          "Fallidos",           "✗", COLORS["error"]),
            ("accounts",        "Cuentas activas",    "◈", COLORS["neon_purple"]),
        ]
        for col, (key, label, icon, color) in enumerate(stats_def):
            card = ctk.CTkFrame(left, **card_frame_style(corner_radius=RADIUS["card"]))
            card.grid(row=0, column=col, sticky="ew",
                      padx=(0 if col == 0 else SPACING["xs"], SPACING["xs"]),
                      pady=(0, SPACING["sm"]))

            ctk.CTkLabel(card, text=icon, font=("Segoe UI", 20),
                         text_color=color).pack(pady=(SPACING["md"], 0))

            val_lbl = ctk.CTkLabel(card, text="—",
                                   font=("Consolas", 30, "bold"),
                                   text_color=color)
            val_lbl.pack()
            ctk.CTkLabel(card, text=label, font=FONTS["small"],
                         text_color=COLORS["text_secondary"]).pack(pady=(0, SPACING["md"]))
            self._stat_labels[key] = val_lbl

        # Feed de actividad reciente
        feed_frame = ctk.CTkFrame(left, **card_frame_style(corner_radius=RADIUS["card"]))
        feed_frame.grid(row=1, column=0, columnspan=4, sticky="nsew")
        feed_frame.grid_columnconfigure(0, weight=1)
        feed_frame.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(feed_frame, text="Actividad reciente",
                     font=FONTS["subheading"], text_color=COLORS["text_primary"],
                     anchor="w").grid(row=0, column=0, sticky="w",
                                      padx=SPACING["md"], pady=SPACING["sm"])

        self._feed_scroll = ctk.CTkScrollableFrame(
            feed_frame, fg_color=COLORS["bg_surface"],
            scrollbar_button_color=COLORS["neon_purple_dim"],
            scrollbar_button_hover_color=COLORS["neon_purple"],
        )
        self._feed_scroll.grid(row=1, column=0, sticky="nsew",
                                padx=SPACING["sm"], pady=(0, SPACING["sm"]))
        self._feed_scroll.grid_columnconfigure(0, weight=1)

        # ── Panel derecho: cuentas conectadas ─────────────────────────────────
        right = ctk.CTkFrame(self, **card_frame_style(corner_radius=RADIUS["card"]))
        right.grid(row=1, column=1, sticky="nsew",
                   padx=(SPACING["xs"], SPACING["lg"]), pady=(0, SPACING["lg"]))
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(right, text="Cuentas conectadas",
                     font=FONTS["subheading"], text_color=COLORS["text_primary"],
                     anchor="w").grid(row=0, column=0, sticky="w",
                                      padx=SPACING["md"], pady=SPACING["sm"])

        self._accounts_scroll = ctk.CTkScrollableFrame(
            right, fg_color=COLORS["bg_panel"],
            scrollbar_button_color=COLORS["neon_purple_dim"],
            scrollbar_button_hover_color=COLORS["neon_purple"],
        )
        self._accounts_scroll.grid(row=1, column=0, sticky="nsew",
                                    padx=SPACING["sm"], pady=(0, SPACING["sm"]))
        self._accounts_scroll.grid_columnconfigure(0, weight=1)

    # ── Datos ─────────────────────────────────────────────────────────────────

    def on_show(self) -> None:
        self._refresh()
        self._schedule_auto_refresh()

    def on_hide(self) -> None:
        if self._refresh_job:
            try:
                self.after_cancel(self._refresh_job)
            except Exception:
                pass
            self._refresh_job = None

    def _schedule_auto_refresh(self) -> None:
        self._refresh_job = self.after(self.REFRESH_INTERVAL_MS, self._auto_refresh)

    def _auto_refresh(self) -> None:
        self._refresh()
        self._schedule_auto_refresh()

    def _refresh(self) -> None:
        threading.Thread(target=self._load_data, daemon=True).start()

    def _load_data(self) -> None:
        try:
            from models.database import (
                ScheduledPost, PostStatus, SocialCredential,
                get_session_factory,
            )
            SessionLocal = get_session_factory()
            db = SessionLocal()
            try:
                today_start = datetime.now(timezone.utc).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )

                published_today = db.query(ScheduledPost).filter(
                    ScheduledPost.status == PostStatus.PUBLISHED.value,
                    ScheduledPost.published_at >= today_start,
                ).count()

                scheduled = db.query(ScheduledPost).filter_by(
                    status=PostStatus.SCHEDULED.value
                ).count()

                failed = db.query(ScheduledPost).filter_by(
                    status=PostStatus.FAILED.value
                ).count()

                accounts = db.query(SocialCredential).filter_by(
                    is_active=True
                ).count()

                # Feed: últimos 25 posts de cualquier estado
                recent_posts = (
                    db.query(ScheduledPost)
                    .order_by(ScheduledPost.updated_at.desc())
                    .limit(25)
                    .all()
                )
                feed_data = []
                for p in recent_posts:
                    hashtags = []
                    if p.hashtags:
                        try:
                            hashtags = json.loads(p.hashtags)
                        except Exception:
                            pass
                    feed_data.append({
                        "id":           p.id,
                        "platform":     p.platform,
                        "content":      p.content,
                        "hashtags":     hashtags,
                        "status":       p.status,
                        "scheduled_at": p.scheduled_at,
                        "published_at": p.published_at,
                        "updated_at":   p.updated_at,
                        "error":        p.error_message,
                    })

                # Cuentas conectadas
                creds = db.query(SocialCredential).all()
                creds_data = [
                    {
                        "platform":     c.platform,
                        "display_name": c.display_name or c.username or c.platform,
                        "is_active":    c.is_active,
                        "expired":      c.is_token_expired(),
                        "expires_at":   c.token_expires_at,
                    }
                    for c in creds
                ]

            finally:
                db.close()

            stats = {
                "published_today": published_today,
                "scheduled":       scheduled,
                "failed":          failed,
                "accounts":        accounts,
            }
            self.after(0, lambda: self._render(stats, feed_data, creds_data))

        except Exception as exc:
            logger.error("Error cargando dashboard: %s", exc)

    def _render(self, stats: dict, feed: list, creds: list) -> None:
        # Stats
        for key, lbl in self._stat_labels.items():
            lbl.configure(text=str(stats.get(key, 0)))

        # Timestamp
        now_str = datetime.now(timezone.utc).strftime("%H:%M UTC")
        self._last_refresh_lbl.configure(text=f"Actualizado {now_str}")

        # Feed
        for w in self._feed_scroll.winfo_children():
            w.destroy()

        if not feed:
            ctk.CTkLabel(
                self._feed_scroll,
                text="Sin actividad aún. Crea tu primer post en el Programador.",
                font=FONTS["small"], text_color=COLORS["text_disabled"],
            ).grid(row=0, column=0, pady=SPACING["xl"])
        else:
            for i, post in enumerate(feed):
                self._render_feed_item(i, post)

        # Cuentas
        for w in self._accounts_scroll.winfo_children():
            w.destroy()

        if not creds:
            ctk.CTkLabel(
                self._accounts_scroll,
                text="Sin cuentas.\nVe a Cuentas para conectar.",
                font=FONTS["small"], text_color=COLORS["text_disabled"],
                justify="center",
            ).grid(row=0, column=0, pady=SPACING["xl"])
        else:
            for i, c in enumerate(creds):
                self._render_account_pill(i, c)

    def _render_feed_item(self, row: int, post: dict) -> None:
        status   = post["status"]
        s_color  = STATUS_COLORS.get(status, COLORS["text_secondary"])
        s_icon   = STATUS_ICONS.get(status, "○")
        platform = post.get("platform", "")
        p_icon   = PLATFORM_ICONS.get(platform, "●")

        item = ctk.CTkFrame(
            self._feed_scroll,
            fg_color=blend_hex(s_color, bg=COLORS["bg_surface"], alpha=0.07),
            corner_radius=RADIUS["btn"],
        )
        item.grid(row=row, column=0, sticky="ew", pady=2, padx=2)
        item.grid_columnconfigure(1, weight=1)

        # Icono de estado
        ctk.CTkLabel(item, text=s_icon, font=FONTS["mono_bold"],
                     text_color=s_color, width=24).grid(
            row=0, column=0, rowspan=2, padx=(SPACING["sm"], 0), pady=SPACING["sm"])

        # Plataforma + timestamp
        top = ctk.CTkFrame(item, fg_color="transparent")
        top.grid(row=0, column=1, sticky="ew", padx=SPACING["xs"])

        ctk.CTkLabel(top, text=f"{p_icon} {platform.upper()}",
                     font=FONTS["badge"], text_color=COLORS.get(platform, COLORS["text_secondary"]),
                     ).pack(side="left")

        # Fecha relevante
        dt = post.get("published_at") or post.get("scheduled_at") or post.get("updated_at")
        if dt:
            try:
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                delta = datetime.now(timezone.utc) - dt
                if delta.total_seconds() < 60:
                    dt_str = "ahora"
                elif delta.total_seconds() < 3600:
                    dt_str = f"hace {int(delta.total_seconds()//60)} min"
                elif delta.days == 0:
                    dt_str = f"hoy {dt.strftime('%H:%M')}"
                else:
                    dt_str = dt.strftime("%d/%m %H:%M")
            except Exception:
                dt_str = ""
            ctk.CTkLabel(top, text=dt_str, font=FONTS["badge"],
                         text_color=COLORS["text_disabled"]).pack(side="right")

        # Contenido truncado
        preview = (post.get("content") or "")[:90].replace("\n", " ")
        if len(post.get("content", "")) > 90:
            preview += "…"
        ctk.CTkLabel(item, text=preview, font=FONTS["small"],
                     text_color=COLORS["text_secondary"], anchor="w",
                     wraplength=420, justify="left").grid(
            row=1, column=1, sticky="ew", padx=SPACING["xs"], pady=(0, SPACING["xs"]))

        # Error si hay
        if post.get("error") and status == "failed":
            ctk.CTkLabel(item, text=f"✗ {post['error'][:60]}",
                         font=FONTS["small"], text_color=COLORS["error"],
                         anchor="w").grid(row=2, column=1, sticky="ew",
                                          padx=SPACING["xs"], pady=(0, SPACING["xs"]))

    def _render_account_pill(self, row: int, cred: dict) -> None:
        platform = cred["platform"]
        p_icon   = PLATFORM_ICONS.get(platform, "●")
        is_ok    = cred["is_active"] and not cred["expired"]
        dot      = "●"
        dot_color = COLORS["success"] if is_ok else (
            COLORS["warning"] if cred["is_active"] else COLORS["error"]
        )

        pill = ctk.CTkFrame(self._accounts_scroll,
                             fg_color=COLORS["bg_surface"],
                             corner_radius=RADIUS["btn"])
        pill.grid(row=row, column=0, sticky="ew", pady=2)

        ctk.CTkLabel(pill, text=dot, font=FONTS["badge"],
                     text_color=dot_color, width=16).pack(side="left", padx=(SPACING["sm"], 0))

        ctk.CTkLabel(pill, text=f"{p_icon}  {cred['display_name'][:18]}",
                     font=FONTS["small"], text_color=COLORS["text_primary"],
                     anchor="w").pack(side="left", padx=SPACING["xs"], pady=SPACING["xs"])

        if cred["expired"]:
            ctk.CTkLabel(pill, text="⚠ expirado", font=FONTS["badge"],
                         text_color=COLORS["warning"]).pack(side="right", padx=SPACING["sm"])
        elif not cred["is_active"]:
            ctk.CTkLabel(pill, text="inactivo", font=FONTS["badge"],
                         text_color=COLORS["text_disabled"]).pack(side="right", padx=SPACING["sm"])
