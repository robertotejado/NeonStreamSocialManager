"""
ui/views/scheduler_view.py — Programador de posts

Funcionalidad:
  • Formulario: plataforma, contenido, hashtags, link, fecha/hora
  • Lista de posts programados con estado visual
  • Publicar ahora / cancelar / editar
  • prefill_content() para recibir texto del AI Lab
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
from datetime import datetime, timezone, timedelta
from typing import Optional

import customtkinter as ctk

from ui.theme import COLORS, FONTS, RADIUS, SPACING, neon_button_style, card_frame_style

logger = logging.getLogger(__name__)

PLATFORMS = ["linkedin", "x_twitter", "tiktok", "telegram", "instagram", "facebook"]
PLATFORMS_LABELS = ["LinkedIn", "X / Twitter", "TikTok", "Telegram", "Instagram", "Facebook"]

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


class SchedulerView(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color=COLORS["bg_deep"], **kwargs)
        self._build()

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=2)
        self.grid_columnconfigure(1, weight=3)
        self.grid_rowconfigure(0, weight=1)

        self._build_form()
        self._build_list()

    # ── Panel izquierdo: formulario ────────────────────────────────────────────

    def _build_form(self) -> None:
        form_container = ctk.CTkFrame(self, fg_color=COLORS["bg_panel"],
                                      border_color=COLORS["border"], border_width=1,
                                      corner_radius=0)
        form_container.grid(row=0, column=0, sticky="nsew")
        form_container.grid_columnconfigure(0, weight=1)
        form_container.grid_rowconfigure(4, weight=1)

        ctk.CTkLabel(form_container, text="◷  Nuevo post",
                     font=FONTS["heading"], text_color=COLORS["neon_cyan"],
                     ).grid(row=0, column=0, sticky="w",
                             padx=SPACING["lg"], pady=(SPACING["lg"], SPACING["sm"]))

        # Plataforma
        ctk.CTkLabel(form_container, text="Plataforma",
                     font=FONTS["small"], text_color=COLORS["text_secondary"],
                     ).grid(row=1, column=0, sticky="w", padx=SPACING["lg"])
        self._platform_var = ctk.StringVar(value="linkedin")
        platform_row = ctk.CTkFrame(form_container, fg_color="transparent")
        platform_row.grid(row=2, column=0, sticky="ew", padx=SPACING["lg"], pady=(2, SPACING["sm"]))

        for plat, label in zip(PLATFORMS, PLATFORMS_LABELS):
            is_active = plat == "linkedin"
            btn = ctk.CTkButton(
                platform_row,
                text=label, width=72, height=28,
                font=FONTS["badge"],
                fg_color=COLORS["neon_purple_dim"] if is_active else COLORS["bg_surface"],
                hover_color=COLORS["neon_purple"],
                text_color=COLORS["text_primary"] if is_active else COLORS["text_secondary"],
                border_color=COLORS["neon_purple"] if is_active else COLORS["border"],
                border_width=1,
                corner_radius=RADIUS["btn"],
                state="normal" if is_active else "disabled",
                command=lambda p=plat: self._select_platform(p),
            )
            btn.pack(side="left", padx=(0, SPACING["xs"]))

        self._plat_buttons = {
            p: platform_row.winfo_children()[i]
            for i, p in enumerate(PLATFORMS)
        }

        # Contenido
        ctk.CTkLabel(form_container, text="Contenido",
                     font=FONTS["small"], text_color=COLORS["text_secondary"],
                     ).grid(row=3, column=0, sticky="w", padx=SPACING["lg"])
        self._content_box = ctk.CTkTextbox(
            form_container, height=140, font=FONTS["body"],
            fg_color=COLORS["bg_input"], wrap="word",
            corner_radius=RADIUS["input"],
        )
        self._content_box.grid(row=4, column=0, sticky="nsew",
                                padx=SPACING["lg"], pady=(2, SPACING["sm"]))
        self._content_box.bind("<KeyRelease>", self._update_char_count)

        self._char_label = ctk.CTkLabel(
            form_container, text="0 / 3000",
            font=FONTS["badge"], text_color=COLORS["text_disabled"], anchor="e",
        )
        self._char_label.grid(row=5, column=0, sticky="e", padx=SPACING["lg"])

        # Hashtags
        ctk.CTkLabel(form_container, text="Hashtags (separados por coma)",
                     font=FONTS["small"], text_color=COLORS["text_secondary"],
                     ).grid(row=6, column=0, sticky="w", padx=SPACING["lg"], pady=(SPACING["sm"], 2))
        self._hashtag_entry = ctk.CTkEntry(
            form_container, placeholder_text="ciberseguridad, ot, ics, linkedin",
            height=32, corner_radius=RADIUS["input"],
        )
        self._hashtag_entry.grid(row=7, column=0, sticky="ew", padx=SPACING["lg"])

        # Link
        ctk.CTkLabel(form_container, text="URL (opcional)",
                     font=FONTS["small"], text_color=COLORS["text_secondary"],
                     ).grid(row=8, column=0, sticky="w", padx=SPACING["lg"], pady=(SPACING["sm"], 2))
        self._link_entry = ctk.CTkEntry(
            form_container, placeholder_text="https://...",
            height=32, corner_radius=RADIUS["input"],
        )
        self._link_entry.grid(row=9, column=0, sticky="ew", padx=SPACING["lg"])

        # Fecha y hora
        ctk.CTkLabel(form_container, text="Programar para",
                     font=FONTS["small"], text_color=COLORS["text_secondary"],
                     ).grid(row=10, column=0, sticky="w", padx=SPACING["lg"], pady=(SPACING["sm"], 2))

        dt_row = ctk.CTkFrame(form_container, fg_color="transparent")
        dt_row.grid(row=11, column=0, sticky="ew", padx=SPACING["lg"], pady=(0, SPACING["sm"]))
        dt_row.grid_columnconfigure((0, 1), weight=1)

        default_dt = datetime.now(timezone.utc) + timedelta(hours=1)
        self._date_entry = ctk.CTkEntry(dt_row, placeholder_text="YYYY-MM-DD",
                                         height=32, corner_radius=RADIUS["input"])
        self._date_entry.insert(0, default_dt.strftime("%Y-%m-%d"))
        self._date_entry.grid(row=0, column=0, sticky="ew", padx=(0, SPACING["xs"]))

        self._time_entry = ctk.CTkEntry(dt_row, placeholder_text="HH:MM (UTC)",
                                         height=32, corner_radius=RADIUS["input"])
        self._time_entry.insert(0, default_dt.strftime("%H:%M"))
        self._time_entry.grid(row=0, column=1, sticky="ew")

        # Botones de acción
        btn_row = ctk.CTkFrame(form_container, fg_color="transparent")
        btn_row.grid(row=12, column=0, sticky="ew",
                     padx=SPACING["lg"], pady=(0, SPACING["lg"]))

        ctk.CTkButton(
            btn_row, text="💾 Guardar borrador", height=36,
            font=FONTS["body"],
            **neon_button_style("neon_cyan"),
            command=lambda: self._save_post(draft=True),
        ).pack(side="left", padx=(0, SPACING["sm"]))

        ctk.CTkButton(
            btn_row, text="📅 Programar", height=36,
            font=FONTS["body"], corner_radius=RADIUS["btn"],
            fg_color=COLORS["neon_purple_dim"], hover_color=COLORS["neon_purple"],
            text_color=COLORS["text_primary"],
            command=lambda: self._save_post(draft=False),
        ).pack(side="left")

        self._form_status = ctk.CTkLabel(
            form_container, text="", font=FONTS["small"],
            text_color=COLORS["text_secondary"],
        )
        self._form_status.grid(row=13, column=0, sticky="w", padx=SPACING["lg"])

    # ── Panel derecho: lista de posts ─────────────────────────────────────────

    def _build_list(self) -> None:
        list_container = ctk.CTkFrame(self, fg_color=COLORS["bg_deep"])
        list_container.grid(row=0, column=1, sticky="nsew")
        list_container.grid_columnconfigure(0, weight=1)
        list_container.grid_rowconfigure(1, weight=1)

        # Toolbar
        toolbar = ctk.CTkFrame(list_container, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew",
                     padx=SPACING["lg"], pady=(SPACING["lg"], SPACING["sm"]))

        ctk.CTkLabel(toolbar, text="Posts programados",
                     font=FONTS["heading"], text_color=COLORS["text_primary"],
                     ).pack(side="left")

        ctk.CTkButton(
            toolbar, text="↺", width=32, height=28,
            font=FONTS["body"],
            **neon_button_style("neon_cyan"),
            command=self._refresh_list,
        ).pack(side="right")

        # Filter tabs
        filter_row = ctk.CTkFrame(list_container, fg_color="transparent")
        filter_row.grid(row=0, column=0, sticky="e",
                        padx=SPACING["lg"], pady=(SPACING["lg"], SPACING["sm"]))
        self._filter_var = ctk.StringVar(value="all")
        for f_val, f_label in [("all", "Todos"), ("scheduled", "Programados"),
                                ("published", "Publicados"), ("failed", "Fallidos")]:
            ctk.CTkButton(
                filter_row, text=f_label, width=80, height=26,
                font=FONTS["badge"], corner_radius=RADIUS["btn"],
                fg_color="transparent", hover_color=COLORS["bg_hover"],
                text_color=COLORS["text_secondary"], border_width=0,
                command=lambda v=f_val: self._apply_filter(v),
            ).pack(side="left", padx=2)

        # Lista scrollable
        self._post_scroll = ctk.CTkScrollableFrame(
            list_container, fg_color=COLORS["bg_deep"],
            scrollbar_button_color=COLORS["neon_purple_dim"],
            scrollbar_button_hover_color=COLORS["neon_purple"],
        )
        self._post_scroll.grid(row=1, column=0, sticky="nsew",
                                padx=SPACING["md"], pady=(0, SPACING["md"]))
        self._post_scroll.grid_columnconfigure(0, weight=1)

        self._filter: Optional[str] = None
        self.after(200, self._refresh_list)

    # ── Lógica ────────────────────────────────────────────────────────────────

    def _select_platform(self, platform: str) -> None:
        self._platform_var.set(platform)
        limits = {"linkedin": 3000, "x_twitter": 280, "tiktok": 2200, "telegram": 4096, "instagram": 2200, "facebook": 63206}
        self._char_limit = limits.get(platform, 3000)
        self._update_char_count()

    def _update_char_count(self, event=None) -> None:
        content = self._content_box.get("1.0", "end").strip()
        limit = getattr(self, "_char_limit", 3000)
        count = len(content)
        color = COLORS["error"] if count > limit else (
            COLORS["warning"] if count > limit * 0.9 else COLORS["text_disabled"]
        )
        self._char_label.configure(text=f"{count} / {limit}", text_color=color)

    def _save_post(self, draft: bool) -> None:
        content = self._content_box.get("1.0", "end").strip()
        if not content:
            self._form_status.configure(text="⚠ El contenido no puede estar vacío.",
                                         text_color=COLORS["warning"])
            return

        hashtag_raw = self._hashtag_entry.get().strip()
        hashtags = [h.strip().lstrip("#") for h in hashtag_raw.split(",") if h.strip()]
        link = self._link_entry.get().strip() or None
        platform = self._platform_var.get()

        scheduled_at = None
        if not draft:
            try:
                date_str = self._date_entry.get().strip()
                time_str = self._time_entry.get().strip()
                dt_str   = f"{date_str}T{time_str}:00+00:00"
                scheduled_at = datetime.fromisoformat(dt_str)
                if scheduled_at <= datetime.now(timezone.utc):
                    self._form_status.configure(text="⚠ La fecha debe ser futura.",
                                                 text_color=COLORS["warning"])
                    return
            except ValueError:
                self._form_status.configure(text="⚠ Formato de fecha inválido (YYYY-MM-DD HH:MM).",
                                             text_color=COLORS["warning"])
                return

        def _do_save():
            try:
                from models.database import (
                    ScheduledPost, PostStatus, SocialCredential,
                    SocialPlatform, AuditAction, AuditLog, get_session_factory,
                )
                from services.scheduler import schedule_post

                SessionLocal = get_session_factory()
                db = SessionLocal()
                try:
                    cred = db.query(SocialCredential).filter_by(
                        platform=platform, is_active=True
                    ).first()

                    if not cred:
                        self.after(0, lambda: self._form_status.configure(
                            text=f"⚠ No hay cuenta conectada para {platform}.",
                            text_color=COLORS["warning"]))
                        return

                    status = PostStatus.DRAFT if draft else PostStatus.SCHEDULED

                    post = ScheduledPost(
                        credential_id=cred.id,
                        platform=platform,
                        content=content,
                        hashtags=json.dumps(hashtags) if hashtags else None,
                        link_url=link,
                        scheduled_at=scheduled_at,
                        status=status,
                    )
                    db.add(post)
                    db.flush()

                    if not draft and scheduled_at:
                        job_id = schedule_post(post.id, scheduled_at)
                        post.scheduler_job_id = job_id

                    db.add(AuditLog(action=AuditAction.POST_CREATED,
                                    platform=platform, entity_id=post.id))
                    db.commit()

                    msg = "✓ Borrador guardado." if draft else f"✓ Programado para {scheduled_at.strftime('%d/%m %H:%M')} UTC."
                    self.after(0, lambda: self._form_status.configure(
                        text=msg, text_color=COLORS["success"]))
                    self.after(0, self._refresh_list)
                    self.after(0, self._clear_form)
                finally:
                    db.close()
            except Exception as exc:
                logger.exception("Error guardando post: %s", exc)
                self.after(0, lambda: self._form_status.configure(
                    text=f"✗ Error: {str(exc)[:60]}", text_color=COLORS["error"]))

        threading.Thread(target=_do_save, daemon=True).start()

    def _clear_form(self) -> None:
        self._content_box.delete("1.0", "end")
        self._hashtag_entry.delete(0, "end")
        self._link_entry.delete(0, "end")
        self.after(3000, lambda: self._form_status.configure(text=""))

    def _apply_filter(self, f: str) -> None:
        self._filter = None if f == "all" else f
        self._refresh_list()

    def _refresh_list(self) -> None:
        def _load():
            try:
                from models.database import ScheduledPost, get_session_factory
                SessionLocal = get_session_factory()
                db = SessionLocal()
                try:
                    query = db.query(ScheduledPost)
                    if self._filter:
                        query = query.filter_by(status=self._filter)
                    posts = query.order_by(ScheduledPost.created_at.desc()).limit(50).all()
                    data = []
                    for p in posts:
                        hashtags = []
                        if p.hashtags:
                            try: hashtags = json.loads(p.hashtags)
                            except: pass
                        data.append({
                            "id":           p.id,
                            "platform":     p.platform,
                            "content":      p.content,
                            "hashtags":     hashtags,
                            "status":       p.status,
                            "scheduled_at": p.scheduled_at,
                            "published_at": p.published_at,
                            "error":        p.error_message,
                        })
                finally:
                    db.close()
                self.after(0, lambda: self._render_list(data))
            except Exception as exc:
                logger.error("Error cargando posts: %s", exc)

        threading.Thread(target=_load, daemon=True).start()

    def _render_list(self, posts: list[dict]) -> None:
        for w in self._post_scroll.winfo_children():
            w.destroy()

        if not posts:
            ctk.CTkLabel(self._post_scroll, text="No hay posts aún",
                         font=FONTS["body"], text_color=COLORS["text_disabled"],
                         ).grid(row=0, column=0, pady=SPACING["xl"])
            return

        for i, post in enumerate(posts):
            card = ctk.CTkFrame(self._post_scroll, **card_frame_style())
            card.grid(row=i, column=0, sticky="ew", pady=SPACING["xs"])
            card.grid_columnconfigure(0, weight=1)

            status     = post["status"]
            s_color    = STATUS_COLORS.get(status, COLORS["text_secondary"])
            s_icon     = STATUS_ICONS.get(status, "○")
            platform   = post["platform"]

            # Header de la tarjeta
            hdr = ctk.CTkFrame(card, fg_color="transparent")
            hdr.grid(row=0, column=0, sticky="ew", padx=SPACING["sm"], pady=(SPACING["sm"], 0))

            ctk.CTkLabel(hdr, text=f"{s_icon} {status.upper()}",
                         font=FONTS["badge"], text_color=s_color).pack(side="left")
            ctk.CTkLabel(hdr, text=platform.upper(),
                         font=FONTS["badge"],
                         text_color=COLORS.get(platform, COLORS["text_secondary"]),
                         ).pack(side="left", padx=SPACING["sm"])

            if post["scheduled_at"]:
                dt_str = post["scheduled_at"].strftime("%d/%m/%Y %H:%M UTC")
                ctk.CTkLabel(hdr, text=dt_str, font=FONTS["badge"],
                             text_color=COLORS["text_secondary"]).pack(side="right")

            # Contenido truncado
            preview = post["content"][:120].replace("\n", " ")
            if len(post["content"]) > 120:
                preview += "…"
            ctk.CTkLabel(card, text=preview, font=FONTS["small"],
                         text_color=COLORS["text_primary"], anchor="w",
                         wraplength=500, justify="left",
                         ).grid(row=1, column=0, sticky="ew",
                                padx=SPACING["md"], pady=(SPACING["xs"], 0))

            # Error si existe
            if post.get("error"):
                ctk.CTkLabel(card, text=f"✗ {post['error'][:80]}",
                             font=FONTS["small"], text_color=COLORS["error"],
                             anchor="w",
                             ).grid(row=2, column=0, sticky="ew", padx=SPACING["md"])

            # Hashtags
            if post["hashtags"]:
                tags_str = "  ".join(f"#{h}" for h in post["hashtags"][:5])
                ctk.CTkLabel(card, text=tags_str, font=FONTS["badge"],
                             text_color=COLORS["neon_cyan"], anchor="w",
                             ).grid(row=3, column=0, sticky="ew",
                                    padx=SPACING["md"], pady=(0, SPACING["xs"]))

            # Botón publicar ahora (solo para draft/scheduled)
            if status in ("draft", "scheduled"):
                ctk.CTkButton(
                    card, text="▶ Publicar ahora", height=26, width=130,
                    font=FONTS["badge"], corner_radius=RADIUS["btn"],
                    fg_color=COLORS["neon_purple_dim"], hover_color=COLORS["neon_purple"],
                    text_color=COLORS["text_primary"],
                    command=lambda pid=post["id"]: self._publish_now(pid),
                ).grid(row=4, column=0, sticky="e",
                       padx=SPACING["sm"], pady=(0, SPACING["sm"]))

    def _publish_now(self, post_id: int) -> None:
        def _do():
            try:
                import asyncio
                from models.database import (
                    ScheduledPost, PostStatus, get_session_factory
                )
                from services.scheduler import schedule_post
                from datetime import timedelta

                SessionLocal = get_session_factory()
                db = SessionLocal()
                try:
                    post = db.query(ScheduledPost).filter_by(id=post_id).first()
                    if post:
                        run_at = datetime.now(timezone.utc) + timedelta(seconds=5)
                        job_id = schedule_post(post.id, run_at)
                        post.scheduled_at     = run_at
                        post.status           = PostStatus.SCHEDULED
                        post.scheduler_job_id = job_id
                        db.commit()
                finally:
                    db.close()
                self.after(0, self._refresh_list)
            except Exception as exc:
                logger.error("Error en publish now: %s", exc)

        threading.Thread(target=_do, daemon=True).start()

    def prefill_content(self, content: str) -> None:
        """Rellena el formulario con contenido recibido del AI Lab."""
        self._content_box.delete("1.0", "end")
        self._content_box.insert("1.0", content)
        self._update_char_count()

    def on_show(self) -> None:
        self._refresh_list()
