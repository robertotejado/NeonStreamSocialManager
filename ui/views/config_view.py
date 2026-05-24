"""
ui/views/config_view.py — Panel de configuración de credenciales de API

Permite al usuario introducir y guardar las API keys de cada plataforma
directamente desde la UI, sin tocar el .env a mano.

Estructura:
  • Tab por plataforma: Gemini, LinkedIn, X/Twitter, TikTok, Telegram, Instagram
  • Cada tab: campos de texto (con toggle show/hide para secretos)
  • Botón "Guardar y recargar" por plataforma
  • Indicador visual de estado (configurado / faltan credenciales)
  • Links directos a los portales de desarrolladores
"""
from __future__ import annotations

import logging
import threading
import webbrowser
from typing import Optional

import customtkinter as ctk

from ui.theme import (
    COLORS, FONTS, RADIUS, SPACING,
    card_frame_style, neon_button_style, blend_hex,
)

logger = logging.getLogger(__name__)

# Definición de plataformas y sus campos
PLATFORM_CONFIG = [
    {
        "id":      "gemini",
        "label":   "Google Gemini",
        "icon":    "✦",
        "color":   "#4285f4",
        "portal":  "https://aistudio.google.com/app/apikey",
        "portal_label": "Google AI Studio →",
        "desc":    "Necesario para el AI Content Lab (generación de posts, análisis…)",
        "fields": [
            {"key": "GEMINI_API_KEY",  "label": "API Key",  "secret": True,
             "placeholder": "AIzaSy..."},
            {"key": "GEMINI_MODEL",    "label": "Modelo",   "secret": False,
             "placeholder": "gemini-1.5-flash"},
        ],
    },
    {
        "id":      "linkedin",
        "label":   "LinkedIn",
        "icon":    "in",
        "color":   "#0a66c2",
        "portal":  "https://www.linkedin.com/developers/apps",
        "portal_label": "LinkedIn Developer Portal →",
        "desc":    "Crea una app en el portal y añade los permisos: openid, profile, email, w_member_social",
        "fields": [
            {"key": "LINKEDIN_CLIENT_ID",     "label": "Client ID",     "secret": False, "placeholder": "78abc123..."},
            {"key": "LINKEDIN_CLIENT_SECRET",  "label": "Client Secret", "secret": True,  "placeholder": "••••••••"},
            {"key": "LINKEDIN_REDIRECT_URI",   "label": "Redirect URI",  "secret": False,
             "placeholder": "http://127.0.0.1:8000/auth/linkedin/callback"},
        ],
    },
    {
        "id":      "x_twitter",
        "label":   "X / Twitter",
        "icon":    "𝕏",
        "color":   "#1da1f2",
        "portal":  "https://developer.twitter.com/en/portal/projects-and-apps",
        "portal_label": "Twitter Developer Portal →",
        "desc":    "Necesitas acceso Basic o Elevated. Activa OAuth2 con PKCE y añade el Redirect URI.",
        "fields": [
            {"key": "X_CLIENT_ID",      "label": "Client ID",     "secret": False, "placeholder": "abc123..."},
            {"key": "X_CLIENT_SECRET",  "label": "Client Secret", "secret": True,  "placeholder": "••••••••"},
            {"key": "X_REDIRECT_URI",   "label": "Redirect URI",  "secret": False,
             "placeholder": "http://127.0.0.1:8000/auth/x/callback"},
        ],
    },
    {
        "id":      "tiktok",
        "label":   "TikTok",
        "icon":    "♪",
        "color":   "#ff0050",
        "portal":  "https://developers.tiktok.com/",
        "portal_label": "TikTok Developer Portal →",
        "desc":    "Crea una app de tipo 'Web' y solicita los scopes: user.info.basic, video.publish",
        "fields": [
            {"key": "TIKTOK_CLIENT_KEY",    "label": "Client Key",    "secret": False, "placeholder": "aw1234..."},
            {"key": "TIKTOK_CLIENT_SECRET", "label": "Client Secret", "secret": True,  "placeholder": "••••••••"},
            {"key": "TIKTOK_REDIRECT_URI",  "label": "Redirect URI",  "secret": False,
             "placeholder": "http://127.0.0.1:8000/auth/tiktok/callback"},
        ],
    },
    {
        "id":      "telegram",
        "label":   "Telegram",
        "icon":    "✈",
        "color":   "#229ed9",
        "portal":  "https://t.me/BotFather",
        "portal_label": "Abrir @BotFather en Telegram →",
        "desc":    "Habla con @BotFather, crea un bot con /newbot y copia el token. Añade el bot a tu canal/grupo como admin.",
        "fields": [
            {"key": "TELEGRAM_BOT_TOKEN",       "label": "Bot Token",        "secret": True,
             "placeholder": "1234567890:AABBcc..."},
            {"key": "TELEGRAM_DEFAULT_CHAT_ID",  "label": "Chat / Channel ID","secret": False,
             "placeholder": "-100123456789  (o @mi_canal)"},
        ],
    },
    {
        "id":      "instagram",
        "label":   "Instagram / Meta",
        "icon":    "◉",
        "color":   "#e1306c",
        "portal":  "https://developers.facebook.com/apps/",
        "portal_label": "Meta Developer Portal →",
        "desc":    "Requiere una app de Meta con los productos: Instagram Graph API y Facebook Login.",
        "fields": [
            {"key": "META_APP_ID",      "label": "App ID",      "secret": False, "placeholder": "1234567890"},
            {"key": "META_APP_SECRET",  "label": "App Secret",  "secret": True,  "placeholder": "••••••••"},
            {"key": "META_REDIRECT_URI","label": "Redirect URI","secret": False,
             "placeholder": "http://127.0.0.1:8000/auth/meta/callback"},
        ],
    },
]


class ConfigView(ctk.CTkFrame):
    """Vista de configuración de credenciales de API."""

    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color=COLORS["bg_deep"], **kwargs)
        self._entries: dict[str, ctk.CTkEntry] = {}
        self._status_labels: dict[str, ctk.CTkLabel] = {}
        self._build()

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Header
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew",
                 padx=SPACING["lg"], pady=(SPACING["lg"], SPACING["sm"]))

        ctk.CTkLabel(hdr, text="⚙  Credenciales de API",
                     font=FONTS["title"], text_color=COLORS["neon_yellow"]).pack(side="left")

        ctk.CTkLabel(
            hdr,
            text="Las claves se guardan en el archivo .env local. Nunca se suben a Internet.",
            font=FONTS["small"], text_color=COLORS["text_disabled"],
        ).pack(side="left", padx=(SPACING["md"], 0), pady=(6, 0))

        # Tabs
        self._tabs = ctk.CTkTabview(
            self,
            fg_color=COLORS["bg_panel"],
            segmented_button_fg_color=COLORS["bg_surface"],
            segmented_button_selected_color=COLORS["neon_yellow"] + "55" if False else COLORS["neon_purple_dim"],
            segmented_button_selected_hover_color=COLORS["neon_purple"],
            segmented_button_unselected_color=COLORS["bg_surface"],
            segmented_button_unselected_hover_color=COLORS["bg_hover"],
            text_color=COLORS["text_secondary"],
            corner_radius=RADIUS["card"],
        )
        self._tabs.grid(row=1, column=0, sticky="nsew",
                        padx=SPACING["lg"], pady=(0, SPACING["lg"]))

        for pdef in PLATFORM_CONFIG:
            self._tabs.add(pdef["label"])
            self._build_platform_tab(pdef)

    def _build_platform_tab(self, pdef: dict) -> None:
        tab = self._tabs.tab(pdef["label"])
        tab.grid_columnconfigure(0, weight=1)

        # Card principal
        card = ctk.CTkFrame(tab, **card_frame_style(corner_radius=RADIUS["card"]))
        card.grid(row=0, column=0, sticky="ew", padx=SPACING["md"], pady=SPACING["md"])
        card.grid_columnconfigure(1, weight=1)

        # Header de la card
        hdr = ctk.CTkFrame(card, fg_color="transparent")
        hdr.grid(row=0, column=0, columnspan=2, sticky="ew",
                 padx=SPACING["md"], pady=(SPACING["md"], 0))

        ctk.CTkLabel(
            hdr,
            text=f"{pdef['icon']}  {pdef['label']}",
            font=FONTS["heading"],
            text_color=pdef["color"],
        ).pack(side="left")

        # Indicador de estado
        status_lbl = ctk.CTkLabel(hdr, text="",
                                   font=FONTS["badge"], text_color=COLORS["text_disabled"])
        status_lbl.pack(side="right")
        self._status_labels[pdef["id"]] = status_lbl

        # Descripción
        ctk.CTkLabel(
            card, text=pdef["desc"],
            font=FONTS["small"], text_color=COLORS["text_secondary"],
            anchor="w", wraplength=600, justify="left",
        ).grid(row=1, column=0, columnspan=2, sticky="ew",
               padx=SPACING["md"], pady=(SPACING["xs"], SPACING["sm"]))

        # Campos de entrada
        for row_i, field in enumerate(pdef["fields"]):
            key = field["key"]

            ctk.CTkLabel(
                card, text=field["label"],
                font=FONTS["small"], text_color=COLORS["text_secondary"], anchor="w",
            ).grid(row=row_i * 2 + 2, column=0, columnspan=2, sticky="w",
                   padx=SPACING["md"], pady=(SPACING["sm"], 2))

            entry_row = ctk.CTkFrame(card, fg_color="transparent")
            entry_row.grid(row=row_i * 2 + 3, column=0, columnspan=2, sticky="ew",
                           padx=SPACING["md"], pady=(0, 0))
            entry_row.grid_columnconfigure(0, weight=1)

            entry = ctk.CTkEntry(
                entry_row,
                placeholder_text=field.get("placeholder", ""),
                height=34,
                corner_radius=RADIUS["input"],
                show="•" if field["secret"] else "",
                font=FONTS["mono"] if field["secret"] else FONTS["body"],
            )
            entry.grid(row=0, column=0, sticky="ew")
            self._entries[key] = entry

            # Toggle mostrar/ocultar para secretos
            if field["secret"]:
                def _make_toggle(e, k):
                    def _toggle():
                        e.configure(show="" if e.cget("show") == "•" else "•")
                    return _toggle
                ctk.CTkButton(
                    entry_row, text="👁", width=34, height=34,
                    font=FONTS["small"],
                    fg_color=COLORS["bg_surface"],
                    hover_color=COLORS["bg_hover"],
                    text_color=COLORS["text_secondary"],
                    corner_radius=RADIUS["input"],
                    command=_make_toggle(entry, key),
                ).grid(row=0, column=1, padx=(SPACING["xs"], 0))

        last_row = len(pdef["fields"]) * 2 + 2

        # Separador
        ctk.CTkFrame(card, height=1, fg_color=COLORS["border"]).grid(
            row=last_row, column=0, columnspan=2, sticky="ew",
            padx=SPACING["md"], pady=SPACING["md"])

        # Botones
        btn_row = ctk.CTkFrame(card, fg_color="transparent")
        btn_row.grid(row=last_row + 1, column=0, columnspan=2, sticky="ew",
                     padx=SPACING["md"], pady=(0, SPACING["md"]))

        ctk.CTkButton(
            btn_row,
            text=f"💾 Guardar {pdef['label']}",
            font=FONTS["body"], height=36,
            fg_color=COLORS["neon_purple_dim"],
            hover_color=COLORS["neon_purple"],
            text_color=COLORS["text_primary"],
            corner_radius=RADIUS["btn"],
            command=lambda p=pdef: self._save_platform(p),
        ).pack(side="left")

        # Botón de verificación para Gemini y Telegram
        if pdef["id"] in ("gemini", "telegram"):
            ctk.CTkButton(
                btn_row,
                text="🔍 Verificar",
                font=FONTS["small"], height=36, width=110,
                **neon_button_style("neon_yellow", corner_radius=RADIUS["btn"]),
                command=lambda p=pdef: self._verify_platform(p),
            ).pack(side="left", padx=(SPACING["xs"], 0))

        ctk.CTkButton(
            btn_row,
            text=pdef["portal_label"],
            font=FONTS["small"], height=36, width=220,
            **neon_button_style("neon_cyan", corner_radius=RADIUS["btn"]),
            command=lambda url=pdef["portal"]: webbrowser.open(url),
        ).pack(side="left", padx=(SPACING["sm"], 0))

        self._save_feedback = {}  # key: feedback label per platform

        feedback = ctk.CTkLabel(btn_row, text="", font=FONTS["small"],
                                 text_color=COLORS["success"])
        feedback.pack(side="right")
        self._save_feedback[pdef["id"]] = feedback

    # ── Datos ─────────────────────────────────────────────────────────────────

    def on_show(self) -> None:
        self._load_all_values()
        self._update_all_status()

    def _load_all_values(self) -> None:
        """Carga los valores actuales del .env en los campos."""
        from services.env_manager import get_env_manager
        mgr  = get_env_manager()
        vals = mgr.read_all()

        for key, entry in self._entries.items():
            value = vals.get(key, "")
            entry.delete(0, "end")
            if value:
                entry.insert(0, value)

    def _update_all_status(self) -> None:
        """Actualiza los indicadores de estado de todas las plataformas."""
        from services.env_manager import get_env_manager
        mgr = get_env_manager()
        for pdef in PLATFORM_CONFIG:
            lbl = self._status_labels.get(pdef["id"])
            if not lbl:
                continue
            if mgr.has_credentials(pdef["id"]):
                lbl.configure(text="✓ Configurado", text_color=COLORS["success"])
            else:
                lbl.configure(text="⚠ Sin credenciales", text_color=COLORS["warning"])

    def _save_platform(self, pdef: dict) -> None:
        """Guarda los campos de una plataforma en el .env."""
        from services.env_manager import get_env_manager
        mgr = get_env_manager()

        values = {}
        for field in pdef["fields"]:
            key   = field["key"]
            entry = self._entries.get(key)
            if entry:
                val = entry.get().strip()
                if val:
                    values[key] = val

        if not values:
            self._show_feedback(pdef["id"], "⚠ Ningún campo rellenado", COLORS["warning"])
            return

        def _do_save():
            results = mgr.set_many(values)
            mgr.reload_config()
            saved   = sum(1 for ok in results.values() if ok)
            self.after(0, lambda: self._after_save(pdef["id"], saved, len(values)))

        threading.Thread(target=_do_save, daemon=True).start()

    def _after_save(self, platform_id: str, saved: int, total: int) -> None:
        msg   = f"✓ {saved}/{total} campos guardados"
        color = COLORS["success"] if saved == total else COLORS["warning"]
        self._show_feedback(platform_id, msg, color)
        self._update_all_status()

    def _verify_platform(self, pdef: dict) -> None:
        """Verifica en tiempo real que las credenciales guardadas funcionan."""
        import threading
        platform_id = pdef["id"]
        self._show_feedback(platform_id, "⏳ Verificando…", COLORS["neon_cyan"])

        def _do_verify():
            import asyncio
            try:
                if platform_id == "gemini":
                    from services.gemini_ai import GeminiAIService, _gemini_instance
                    import services.gemini_ai as ai_mod
                    ai_mod._gemini_instance = None  # Forzar re-init con nueva key
                    svc = GeminiAIService()
                    # Test mínimo: llamada con prompt vacío
                    asyncio.run(svc._generate("Responde solo: OK"))
                    msg, color = "✓ Gemini API key válida", COLORS["success"]

                elif platform_id == "telegram":
                    from providers.telegram import create_telegram_provider
                    provider = create_telegram_provider()
                    ok, info = asyncio.run(provider.verify_bot_token())
                    if ok:
                        msg, color = f"✓ Bot verificado: {info}", COLORS["success"]
                    else:
                        msg, color = f"✗ {info}", COLORS["error"]
                else:
                    msg, color = "Verificación no disponible para esta plataforma", COLORS["text_secondary"]

            except Exception as exc:
                msg   = f"✗ {str(exc)[:60]}"
                color = COLORS["error"]

            self.after(0, lambda m=msg, c=color: self._show_feedback(platform_id, m, c))

        threading.Thread(target=_do_verify, daemon=True).start()

    def _show_feedback(self, platform_id: str, msg: str, color: str) -> None:
        lbl = self._save_feedback.get(platform_id)
        if lbl:
            lbl.configure(text=msg, text_color=color)
            self.after(4000, lambda: lbl.configure(text=""))
