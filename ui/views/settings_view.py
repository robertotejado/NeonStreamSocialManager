"""
ui/views/settings_view.py — Gestión de cuentas OAuth2

Permite al usuario:
  • Ver qué cuentas están conectadas con su estado y expiración de token
  • Conectar una nueva cuenta (inicia el flujo OAuth via OAuthBridge)
  • Desconectar una cuenta (revoca token y borra de DB)
  • Refrescar tokens manualmente
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable, Optional

import customtkinter as ctk

from ui.theme import COLORS, FONTS, RADIUS, SPACING, neon_button_style, card_frame_style, danger_button_style, platform_color, blend_hex

logger = logging.getLogger(__name__)

PLATFORM_DEFS = [
    {
        "id":    "linkedin",
        "label": "LinkedIn",
        "icon":  "in",
        "desc":  "Publica posts de texto, imágenes y artículos",
        "phase": "PoC",
    },
    {
        "id":    "x_twitter",
        "label": "X / Twitter",
        "icon":  "𝕏",
        "desc":  "Tweets, hilos y respuestas",
        "phase": "Fase 2",
    },
    {
        "id":    "instagram",
        "label": "Instagram",
        "icon":  "◉",
        "desc":  "Posts de imagen y Reels (requiere cuenta Business)",
        "phase": "Fase 4",
    },
    {
        "id":    "facebook",
        "label": "Facebook",
        "icon":  "f",
        "desc":  "Posts en páginas y perfiles",
        "phase": "Fase 3",
    },
    {
        "id":    "telegram",
        "label": "Telegram",
        "icon":  "✈",
        "desc":  "Publica en canales y grupos via Bot API",
        "phase": "Fase 3",
    },
]


class SettingsView(ctk.CTkFrame):
    """Vista de gestión de cuentas y ajustes de la aplicación."""

    def __init__(
        self,
        master,
        on_accounts_changed: Optional[Callable] = None,
        **kwargs,
    ):
        super().__init__(master, fg_color=COLORS["bg_deep"], **kwargs)
        self._on_accounts_changed = on_accounts_changed
        self._account_cards: dict[str, "_AccountCard"] = {}
        self._build()
        self.after(100, self._refresh_accounts)  # Cargar datos al aparecer

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Header
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew",
                    padx=SPACING["lg"], pady=(SPACING["lg"], SPACING["sm"]))

        ctk.CTkLabel(header, text="⬡  Cuentas conectadas",
                     font=FONTS["title"], text_color=COLORS["neon_purple"],
                     ).pack(side="left")

        ctk.CTkButton(
            header, text="↺ Refrescar", width=100, height=30,
            font=FONTS["small"],
            **neon_button_style("neon_cyan"),
            command=self._refresh_accounts,
        ).pack(side="right")

        # Scroll de tarjetas de plataformas
        self._scroll = ctk.CTkScrollableFrame(
            self, fg_color=COLORS["bg_deep"],
            scrollbar_button_color=COLORS["neon_purple_dim"],
            scrollbar_button_hover_color=COLORS["neon_purple"],
        )
        self._scroll.grid(row=1, column=0, sticky="nsew",
                          padx=SPACING["lg"], pady=(0, SPACING["lg"]))
        self._scroll.grid_columnconfigure(0, weight=1)

        for i, pdef in enumerate(PLATFORM_DEFS):
            card = _AccountCard(
                self._scroll,
                platform_def=pdef,
                on_connect=self._on_connect,
                on_disconnect=self._on_disconnect,
            )
            card.grid(row=i, column=0, sticky="ew", pady=SPACING["xs"])
            self._account_cards[pdef["id"]] = card

    # ── Lógica de datos ───────────────────────────────────────────────────────

    def _refresh_accounts(self) -> None:
        """Recarga el estado de las cuentas desde la DB."""
        try:
            from models.database import SocialCredential, get_session_factory
            SessionLocal = get_session_factory()
            db = SessionLocal()
            try:
                credentials = db.query(SocialCredential).all()
                cred_by_platform = {c.platform: c for c in credentials}
            finally:
                db.close()

            for platform_id, card in self._account_cards.items():
                cred = cred_by_platform.get(platform_id)
                card.update_state(cred)

            if self._on_accounts_changed:
                accounts = [
                    {
                        "platform":     c.platform,
                        "display_name": c.display_name,
                        "username":     c.username,
                        "is_active":    c.is_active,
                    }
                    for c in cred_by_platform.values()
                    if c.is_active
                ]
                self._on_accounts_changed(accounts)

        except Exception as exc:
            logger.error("Error refrescando cuentas: %s", exc)

    def _on_connect(self, platform_id: str) -> None:
        """Inicia el flujo de conexión para una plataforma."""
        # Telegram usa Bot Token — verificar directamente sin OAuth
        if platform_id == "telegram":
            self._on_connect_telegram()
            return

        try:
            from services.oauth_bridge import get_oauth_bridge
            bridge = get_oauth_bridge()

            card = self._account_cards.get(platform_id)
            if card:
                card.set_connecting(True)

            def on_complete(result: dict) -> None:
                self.after(0, lambda: self._on_oauth_complete(platform_id, result))

            def on_error(msg: str) -> None:
                self.after(0, lambda: self._on_oauth_error(platform_id, msg))

            bridge.start_oauth_flow(platform_id, on_complete=on_complete, on_error=on_error)

        except Exception as exc:
            self._on_oauth_error(platform_id, str(exc))

    def _on_connect_telegram(self) -> None:
        """Conecta Telegram verificando el Bot Token del .env."""
        import threading, asyncio

        card = self._account_cards.get("telegram")
        if card:
            card.set_connecting(True)

        def _do_verify():
            try:
                from providers.telegram import create_telegram_provider
                from models.database import (
                    SocialCredential, SocialPlatform,
                    AuditAction, AuditLog, get_session_factory,
                )
                from datetime import datetime, timezone

                provider = create_telegram_provider()
                ok, info  = asyncio.run(provider.verify_bot_token())

                if not ok:
                    err_msg = f"Token inválido: {info}. Ve a Credenciales y añade el Bot Token."
                    self.after(0, lambda m=err_msg: self._on_oauth_error("telegram", m))
                    return

                profile = asyncio.run(provider.get_user_profile(provider._bot_token))

                SessionLocal = get_session_factory()
                db = SessionLocal()
                try:
                    existing = db.query(SocialCredential).filter_by(
                        platform=SocialPlatform.TELEGRAM,
                        external_user_id=profile.external_user_id,
                    ).first()
                    if existing:
                        existing.access_token = provider._bot_token
                        existing.display_name = profile.display_name
                        existing.username     = profile.username
                        existing.is_active    = True
                        existing.updated_at   = datetime.now(timezone.utc)
                        credential_id = existing.id
                    else:
                        from services.env_manager import get_env_manager
                        token = get_env_manager().get("TELEGRAM_BOT_TOKEN")
                        cred = SocialCredential(
                            platform=SocialPlatform.TELEGRAM,
                            external_user_id=profile.external_user_id,
                            username=profile.username,
                            display_name=profile.display_name,
                            access_token=token,
                            is_active=True,
                        )
                        db.add(cred)
                        db.flush()
                        credential_id = cred.id
                    db.add(AuditLog(action=AuditAction.AUTH_COMPLETED,
                                    platform="telegram", entity_id=credential_id))
                    db.commit()
                finally:
                    db.close()

                result = {"credential_id": credential_id,
                          "display_name": profile.display_name,
                          "username": profile.username}
                self.after(0, lambda: self._on_oauth_complete("telegram", result))

            except Exception as exc:
                self.after(0, lambda e=exc: self._on_oauth_error("telegram", str(e)))

        threading.Thread(target=_do_verify, daemon=True).start()

    def _on_oauth_complete(self, platform_id: str, result: dict) -> None:
        card = self._account_cards.get(platform_id)
        if card:
            card.set_connecting(False)
        self._refresh_accounts()
        logger.info("OAuth completado para %s: %s", platform_id, result)

    def _on_oauth_error(self, platform_id: str, msg: str) -> None:
        card = self._account_cards.get(platform_id)
        if card:
            card.set_connecting(False)
            card.show_error(msg)
        logger.error("OAuth error %s: %s", platform_id, msg)

    def _on_disconnect(self, platform_id: str, credential_id: int) -> None:
        """Revoca el token y desactiva la credencial."""
        import asyncio
        import threading

        async def _revoke():
            try:
                from models.database import (
                    SocialCredential, SocialPlatform,
                    AuditAction, AuditLog, get_session_factory,
                )
                from providers.linkedin import create_linkedin_provider

                SessionLocal = get_session_factory()
                db = SessionLocal()
                try:
                    cred = db.query(SocialCredential).filter_by(id=credential_id).first()
                    if cred and cred.access_token:
                        if platform_id == "linkedin":
                            provider = create_linkedin_provider()
                            await provider.revoke_token(cred.access_token)
                        cred.access_token  = None
                        cred.refresh_token = None
                        cred.is_active     = False
                        db.add(AuditLog(
                            action=AuditAction.TOKEN_REVOKED,
                            platform=platform_id,
                            entity_id=credential_id,
                        ))
                        db.commit()
                finally:
                    db.close()
                self.after(0, self._refresh_accounts)
            except Exception as exc:
                logger.error("Error desconectando %s: %s", platform_id, exc)
                self.after(0, self._refresh_accounts)

        threading.Thread(target=lambda: asyncio.run(_revoke()), daemon=True).start()

    def on_show(self) -> None:
        """Llamar cuando la vista se hace visible."""
        self._refresh_accounts()


class _AccountCard(ctk.CTkFrame):
    """Tarjeta de una plataforma con estado de conexión."""

    def __init__(self, master, platform_def: dict,
                 on_connect: Callable, on_disconnect: Callable, **kwargs):
        super().__init__(master, **card_frame_style(), **kwargs)
        self._pdef         = platform_def
        self._on_connect   = on_connect
        self._on_disconnect = on_disconnect
        self._credential_id: Optional[int] = None
        self._build()

    def _build(self) -> None:
        self.grid_columnconfigure(1, weight=1)

        # Icono de plataforma
        icon_frame = ctk.CTkFrame(
            self, width=52, height=52,
            fg_color=blend_hex(platform_color(self._pdef["id"]), bg=COLORS["bg_surface"]),
            corner_radius=RADIUS["badge"],
        )
        icon_frame.grid(row=0, column=0, rowspan=2, padx=SPACING["md"], pady=SPACING["md"], sticky="ns")
        icon_frame.grid_propagate(False)

        ctk.CTkLabel(
            icon_frame, text=self._pdef["icon"],
            font=("Segoe UI", 20, "bold"),
            text_color=platform_color(self._pdef["id"]),
        ).place(relx=0.5, rely=0.5, anchor="center")

        # Nombre y descripción
        info = ctk.CTkFrame(self, fg_color="transparent")
        info.grid(row=0, column=1, sticky="ew", padx=(0, SPACING["sm"]), pady=(SPACING["md"], 0))

        name_row = ctk.CTkFrame(info, fg_color="transparent")
        name_row.pack(fill="x")

        ctk.CTkLabel(name_row, text=self._pdef["label"],
                     font=FONTS["subheading"], text_color=COLORS["text_primary"],
                     ).pack(side="left")

        phase_badge = ctk.CTkLabel(
            name_row,
            text=f"  {self._pdef['phase']}  ",
            font=FONTS["badge"],
            text_color=COLORS["neon_purple"] if self._pdef["phase"] == "PoC" else COLORS["text_disabled"],
            fg_color=COLORS["bg_surface"],
            corner_radius=RADIUS["badge"],
        )
        phase_badge.pack(side="left", padx=SPACING["sm"])

        ctk.CTkLabel(info, text=self._pdef["desc"],
                     font=FONTS["small"], text_color=COLORS["text_secondary"],
                     anchor="w",
                     ).pack(fill="x")

        # Estado y botones
        action_row = ctk.CTkFrame(self, fg_color="transparent")
        action_row.grid(row=1, column=1, sticky="ew",
                        padx=(0, SPACING["md"]), pady=(0, SPACING["md"]))

        self._status_label = ctk.CTkLabel(
            action_row, text="Sin conectar",
            font=FONTS["small"], text_color=COLORS["text_disabled"],
        )
        self._status_label.pack(side="left")

        self._disconnect_btn = ctk.CTkButton(
            action_row, text="Desconectar", width=100, height=28,
            font=FONTS["small"],
            **danger_button_style(),
            command=self._handle_disconnect,
        )

        self._connect_btn = ctk.CTkButton(
            action_row, text="Conectar", width=100, height=28,
            font=FONTS["small"],
            **neon_button_style("neon_cyan"),
            command=lambda: self._on_connect(self._pdef["id"]),
            state="normal" if self._pdef["phase"] == "PoC" else "disabled",
        )
        self._connect_btn.pack(side="right", padx=(SPACING["sm"], 0))

        self._error_label = ctk.CTkLabel(
            self, text="", font=FONTS["small"],
            text_color=COLORS["error"], wraplength=400, anchor="w",
        )
        self._error_label.grid(row=2, column=1, sticky="ew",
                               padx=(0, SPACING["md"]), pady=(0, SPACING["xs"]))

    def update_state(self, credential=None) -> None:
        if credential and credential.is_active:
            self._credential_id = credential.id
            expired = credential.is_token_expired()
            name    = credential.display_name or credential.username or "Conectado"

            if expired:
                status_text  = f"⚠ Token expirado — {name}"
                status_color = COLORS["warning"]
            else:
                expires_str = ""
                if credential.token_expires_at:
                    delta = credential.token_expires_at - datetime.now(timezone.utc)
                    h = int(delta.total_seconds() // 3600)
                    expires_str = f" (expira en {h}h)" if h > 0 else " (expira pronto)"
                status_text  = f"✓ Conectado como {name}{expires_str}"
                status_color = COLORS["success"]

            self._status_label.configure(text=status_text, text_color=status_color)
            self._connect_btn.pack_forget()
            self._disconnect_btn.pack(side="right", padx=(SPACING["sm"], 0))
        else:
            self._credential_id = None
            self._status_label.configure(text="Sin conectar", text_color=COLORS["text_disabled"])
            self._disconnect_btn.pack_forget()
            can_connect = self._pdef["phase"] in ("PoC", "Fase 2", "Fase 3", "Fase 4")
            self._connect_btn.configure(state="normal" if can_connect else "disabled")
            self._connect_btn.pack(side="right", padx=(SPACING["sm"], 0))

        self._error_label.configure(text="")

    def set_connecting(self, connecting: bool) -> None:
        if connecting:
            self._status_label.configure(text="🔄 Esperando autorización en el navegador…",
                                          text_color=COLORS["neon_cyan"])
            self._connect_btn.configure(state="disabled")
        else:
            self._connect_btn.configure(state="normal")

    def show_error(self, msg: str) -> None:
        self._error_label.configure(text=f"✗ {msg[:120]}")

    def _handle_disconnect(self) -> None:
        if self._credential_id:
            self._on_disconnect(self._pdef["id"], self._credential_id)
