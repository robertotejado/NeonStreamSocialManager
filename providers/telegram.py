"""
providers/telegram.py — Provider Telegram Bot API

Diferente al resto de providers: NO usa OAuth2.
Usa el token del Bot (obtenido de @BotFather) para publicar
en canales, grupos o chats directamente via Bot API.

Flujo de configuración:
  1. Hablar con @BotFather → /newbot → copiar el token
  2. Añadir el bot al canal/grupo como administrador
  3. Obtener el chat_id: {canal: "@mi_canal" o "-100xxxxx"}

Endpoints:
  Base: https://api.telegram.org/bot{TOKEN}/
  • sendMessage      → texto con Markdown/HTML
  • sendPhoto        → imagen + caption
  • sendVideo        → vídeo + caption
  • sendDocument     → archivo
  • getMe            → verificar token
  • getChat          → info del canal/chat

Límites:
  • Texto puro:  4096 caracteres (Markdown/HTML)
  • Caption:     1024 caracteres
  • Foto:        10 MB
  • Vídeo:       50 MB (Bot API), 2 GB (via upload_to_file)
  • Rate limit:  30 mensajes/segundo (1 msg/seg por chat)
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

import httpx

from providers.base import (
    ContentValidationResult, OAuthTokens, PostAnalytics,
    PostContent, PublishResult, SocialMediaProvider, UserProfile,
)

logger = logging.getLogger(__name__)


class TelegramProvider(SocialMediaProvider):
    """
    Provider Telegram via Bot API.
    No implementa OAuth2 (usa bot token directo),
    pero hereda SocialMediaProvider para uniformidad.
    """

    PLATFORM_NAME    = "Telegram"
    MAX_POST_LENGTH  = 4096    # para mensajes de texto
    MAX_CAPTION_LEN  = 1024    # para mensajes con media
    SUPPORTED_MIME_TYPES = [
        "image/jpeg", "image/png", "image/gif", "image/webp",
        "video/mp4",
        "application/pdf",
    ]

    def __init__(
        self,
        bot_token: str,
        default_chat_id: Optional[str] = None,
    ) -> None:
        # Telegram usa bot_token directamente — saltamos la validación de super()
        # que requiere client_id y client_secret no vacíos
        if not bot_token:
            raise ValueError("TelegramProvider: bot_token es obligatorio.")
        self._client_id       = bot_token   # Compatibilidad con base
        self._client_secret   = "telegram"  # Valor no vacío para pasar validación
        self._redirect_uri    = ""
        self._bot_token       = bot_token
        self._default_chat_id = default_chat_id
        self._api_base        = f"https://api.telegram.org/bot{bot_token}"
        self._logger          = __import__("logging").getLogger(
            f"neonstream.providers.{self.PLATFORM_NAME.lower()}"
        )

    # ── OAuth2 stubs (no aplica, Telegram usa bot token) ─────────────────────

    def get_authorization_url(self) -> tuple[str, str]:
        """Telegram no usa OAuth2. Devuelve URL del BotFather."""
        return "https://t.me/BotFather", self._generate_state()

    async def handle_callback(self, code: str, state: str, expected_state: str) -> OAuthTokens:
        """No aplica para Telegram — el token viene de BotFather."""
        raise NotImplementedError("Telegram usa Bot Token, no OAuth2 callback.")

    async def refresh_access_token(self, refresh_token: str) -> OAuthTokens:
        """El bot token de Telegram no expira."""
        return OAuthTokens(access_token=self._bot_token)

    async def revoke_token(self, access_token: str) -> bool:
        """Para revocar: usar @BotFather → /deletebot."""
        return True

    # ── Perfil del bot ────────────────────────────────────────────────────────

    async def get_user_profile(self, access_token: str) -> UserProfile:
        """Obtiene información del bot via getMe."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{self._api_base}/getMe")
        resp.raise_for_status()
        data = resp.json()

        if not data.get("ok"):
            raise PermissionError(
                f"Telegram token inválido: {data.get('description', 'error desconocido')}"
            )

        bot = data["result"]
        return UserProfile(
            external_user_id=str(bot.get("id", "")),
            username=bot.get("username", ""),
            display_name=bot.get("first_name", ""),
            raw_data=bot,
        )

    async def verify_bot_token(self) -> tuple[bool, str]:
        """
        Verifica que el bot token es válido.
        Devuelve (True, "@bot_username") o (False, "mensaje de error").
        """
        try:
            profile = await self.get_user_profile(self._bot_token)
            return True, f"@{profile.username}"
        except Exception as exc:
            return False, str(exc)

    async def get_chat_info(self, chat_id: str) -> dict:
        """Obtiene información de un canal o grupo."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self._api_base}/getChat",
                params={"chat_id": chat_id},
            )
        resp.raise_for_status()
        data = resp.json()
        if data.get("ok"):
            return data["result"]
        raise ValueError(f"No se pudo obtener info del chat {chat_id}: {data.get('description')}")

    # ── Validación ────────────────────────────────────────────────────────────

    def validate_content(self, content: PostContent) -> ContentValidationResult:
        result = ContentValidationResult(is_valid=True)

        has_media = bool(content.media_paths)
        max_len   = self.MAX_CAPTION_LEN if has_media else self.MAX_POST_LENGTH
        text_len  = len(content.full_text)

        if not content.text.strip() and not has_media:
            result.add_error("El mensaje no puede estar vacío.")

        if text_len > max_len:
            result.add_error(
                f"Texto demasiado largo: {text_len}/{max_len} caracteres "
                f"({'con media' if has_media else 'texto puro'})."
            )

        for path in content.media_paths:
            if not os.path.isfile(path):
                result.add_error(f"Archivo no encontrado: {path}")
            else:
                size_mb = os.path.getsize(path) / 1024 / 1024
                ext = os.path.splitext(path)[1].lower()
                if ext in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
                    if size_mb > 10:
                        result.add_error(f"Imagen demasiado grande: {size_mb:.1f} MB (máx 10 MB).")
                elif ext == ".mp4":
                    if size_mb > 50:
                        result.add_error(f"Vídeo demasiado grande: {size_mb:.1f} MB (máx 50 MB via Bot API).")

        return result

    async def upload_media(
        self, access_token: str, media_path: str, mime_type: str
    ) -> str:
        """Telegram no requiere pre-upload — devuelve el path para enviarlo inline."""
        return media_path

    # ── Publicación ───────────────────────────────────────────────────────────

    async def publish_post(
        self,
        access_token: str,
        content: PostContent,
        media_ids: Optional[list[str]] = None,   # En Telegram son paths locales
        chat_id: Optional[str] = None,
    ) -> PublishResult:
        """
        Publica en Telegram. Selecciona automáticamente el método según el contenido:
          • Solo texto → sendMessage
          • 1 imagen   → sendPhoto
          • 1 vídeo    → sendVideo
          • Múltiples  → sendMediaGroup
        """
        target_chat = chat_id or self._default_chat_id
        if not target_chat:
            return PublishResult(
                success=False,
                error_message="No se especificó chat_id. Configura TELEGRAM_DEFAULT_CHAT_ID en el .env.",
            )

        # Determinar tipo de envío
        media_paths = content.media_paths or []
        text        = content.full_text

        try:
            if not media_paths:
                result_data = await self._send_message(target_chat, text)
            elif len(media_paths) == 1:
                result_data = await self._send_single_media(target_chat, media_paths[0], text)
            else:
                result_data = await self._send_media_group(target_chat, media_paths, text)

            msg_id = str(result_data.get("message_id", ""))
            self._logger.info("Mensaje Telegram enviado a %s: id=%s", target_chat, msg_id)

            return PublishResult(
                success=True,
                platform_post_id=msg_id,
                raw_response=result_data,
            )

        except Exception as exc:
            return PublishResult(success=False, error_message=str(exc))

    async def _send_message(self, chat_id: str, text: str) -> dict:
        """Envía un mensaje de texto con formato Markdown."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self._api_base}/sendMessage",
                json={
                    "chat_id":    chat_id,
                    "text":       text,
                    "parse_mode": "Markdown",
                },
            )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram sendMessage error: {data.get('description')}")
        return data["result"]

    async def _send_single_media(
        self, chat_id: str, media_path: str, caption: str
    ) -> dict:
        """Envía una imagen o vídeo con caption."""
        ext    = os.path.splitext(media_path)[1].lower()
        method = "sendVideo" if ext in (".mp4", ".mov") else "sendPhoto"
        field  = "video" if method == "sendVideo" else "photo"

        with open(media_path, "rb") as f:
            files = {field: (os.path.basename(media_path), f)}
            data  = {
                "chat_id":    chat_id,
                "caption":    caption[:self.MAX_CAPTION_LEN],
                "parse_mode": "Markdown",
            }
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    f"{self._api_base}/{method}",
                    data=data, files=files,
                )

        resp.raise_for_status()
        result = resp.json()
        if not result.get("ok"):
            raise RuntimeError(f"Telegram {method} error: {result.get('description')}")
        return result["result"]

    async def _send_media_group(
        self, chat_id: str, media_paths: list[str], caption: str
    ) -> dict:
        """Envía un álbum de hasta 10 archivos (sendMediaGroup)."""
        media_group = []
        file_handles = []

        try:
            files_dict: dict[str, Any] = {}
            for i, path in enumerate(media_paths[:10]):
                ext       = os.path.splitext(path)[1].lower()
                media_type = "video" if ext in (".mp4", ".mov") else "photo"
                attach_key = f"file{i}"
                fh         = open(path, "rb")
                file_handles.append(fh)
                files_dict[attach_key] = (os.path.basename(path), fh)

                item: dict[str, Any] = {
                    "type":  media_type,
                    "media": f"attach://{attach_key}",
                }
                if i == 0 and caption:
                    item["caption"]    = caption[:self.MAX_CAPTION_LEN]
                    item["parse_mode"] = "Markdown"
                media_group.append(item)

            import json
            async with httpx.AsyncClient(timeout=180.0) as client:
                resp = await client.post(
                    f"{self._api_base}/sendMediaGroup",
                    data={"chat_id": chat_id, "media": json.dumps(media_group)},
                    files=files_dict,
                )
        finally:
            for fh in file_handles:
                fh.close()

        resp.raise_for_status()
        result = resp.json()
        if not result.get("ok"):
            raise RuntimeError(f"Telegram sendMediaGroup error: {result.get('description')}")
        # sendMediaGroup devuelve lista de mensajes — devolver el primero
        messages = result["result"]
        return messages[0] if isinstance(messages, list) else result

    # ── Analytics ─────────────────────────────────────────────────────────────

    async def get_post_analytics(
        self, access_token: str, platform_post_id: str
    ) -> PostAnalytics:
        """Telegram Bot API no expone métricas de mensajes."""
        return PostAnalytics(platform_post_id=platform_post_id)


# ── Factory ───────────────────────────────────────────────────────────────────

def create_telegram_provider() -> TelegramProvider:
    from config import get_settings
    s = get_settings()
    if not s.telegram_bot_token:
        raise ValueError(
            "TELEGRAM_BOT_TOKEN no configurado. "
            "Ve a Credenciales → Telegram en NeonStream."
        )
    return TelegramProvider(
        bot_token=s.telegram_bot_token,
        default_chat_id=s.telegram_default_chat_id or None,
    )
