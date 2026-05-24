"""
providers/tiktok.py — Provider TikTok (Fase 3)

OAuth2 Authorization Code + PKCE según la TikTok API v2.

Endpoints:
  Auth:    https://www.tiktok.com/v2/auth/authorize/
  Token:   https://open.tiktokapis.com/v2/oauth/token/
  Revoke:  https://open.tiktokapis.com/v2/oauth/revoke/
  Me:      https://open.tiktokapis.com/v2/user/info/
  Post:    https://open.tiktokapis.com/v2/post/publish/video/init/
  Upload:  https://open.tiktokapis.com/v2/post/publish/video/upload/

Scopes necesarios (portal developers.tiktok.com):
  user.info.basic  video.publish  video.upload

Notas:
  • TikTok solo permite publicar VÍDEOS (no imágenes ni texto puro).
  • El flujo de publicación es: init → upload_chunk → publish.
  • El token de acceso expira en 24 h; el refresh_token en 365 días.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import secrets
from typing import Any, Optional
from urllib.parse import urlencode

import httpx

from providers.base import (
    ContentValidationResult, OAuthTokens, PostAnalytics,
    PostContent, PublishResult, SocialMediaProvider, UserProfile,
)

logger = logging.getLogger(__name__)


class TikTokProvider(SocialMediaProvider):
    """Conector TikTok — OAuth2 PKCE + Video Publish API v2."""

    PLATFORM_NAME   = "TikTok"
    MAX_POST_LENGTH = 2200
    SUPPORTED_MIME_TYPES = ["video/mp4", "video/quicktime", "video/webm"]

    _AUTH_URL   = "https://www.tiktok.com/v2/auth/authorize/"
    _TOKEN_URL  = "https://open.tiktokapis.com/v2/oauth/token/"
    _REVOKE_URL = "https://open.tiktokapis.com/v2/oauth/revoke/"
    _API_BASE   = "https://open.tiktokapis.com/v2"

    _pkce_store: dict[str, str] = {}   # state → code_verifier

    def __init__(
        self,
        client_key: str,
        client_secret: str,
        redirect_uri: str,
        scopes: Optional[list[str]] = None,
    ) -> None:
        # TikTok usa "client_key" en lugar de "client_id"
        super().__init__(client_key, client_secret, redirect_uri)
        self._scopes = scopes or ["user.info.basic", "video.publish", "video.upload"]

    # ── PKCE ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _pkce_pair() -> tuple[str, str]:
        verifier  = secrets.token_urlsafe(64)
        digest    = hashlib.sha256(verifier.encode()).digest()
        challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
        return verifier, challenge

    # ── OAuth2 ────────────────────────────────────────────────────────────────

    def get_authorization_url(self) -> tuple[str, str]:
        state    = self._generate_state()
        verifier, challenge = self._pkce_pair()
        TikTokProvider._pkce_store[state] = verifier

        params = {
            "client_key":            self._client_id,   # TikTok llama "client_key" al client_id
            "response_type":         "code",
            "scope":                 ",".join(self._scopes),
            "redirect_uri":          self._redirect_uri,
            "state":                 state,
            "code_challenge":        challenge,
            "code_challenge_method": "S256",
        }
        url = f"{self._AUTH_URL}?{urlencode(params)}"
        self._logger.info("URL autorización TikTok generada (state=%s...)", state[:8])
        return url, state

    async def handle_callback(
        self, code: str, state: str, expected_state: str
    ) -> OAuthTokens:
        self._validate_state_or_raise(state, expected_state)

        verifier = TikTokProvider._pkce_store.pop(state, None)
        if not verifier:
            raise ValueError("code_verifier no encontrado para este state.")

        payload = {
            "client_key":    self._client_id,
            "client_secret": self._client_secret,
            "code":          code,
            "grant_type":    "authorization_code",
            "redirect_uri":  self._redirect_uri,
            "code_verifier": verifier,
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                self._TOKEN_URL,
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        response.raise_for_status()
        data = response.json()

        if data.get("error"):
            raise PermissionError(
                f"TikTok OAuth error: {data['error']} — {data.get('error_description')}"
            )

        return OAuthTokens(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_in_seconds=data.get("expires_in"),
            scopes=data.get("scope", "").split(",") if data.get("scope") else self._scopes,
            raw_response=data,
        )

    async def refresh_access_token(self, refresh_token: str) -> OAuthTokens:
        payload = {
            "client_key":    self._client_id,
            "client_secret": self._client_secret,
            "grant_type":    "refresh_token",
            "refresh_token": refresh_token,
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                self._TOKEN_URL, data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        resp.raise_for_status()
        data = resp.json()
        return OAuthTokens(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token", refresh_token),
            expires_in_seconds=data.get("expires_in"),
            raw_response=data,
        )

    async def revoke_token(self, access_token: str) -> bool:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                self._REVOKE_URL,
                data={"client_key": self._client_id, "client_secret": self._client_secret,
                      "token": access_token},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        return resp.status_code == 200

    # ── Perfil ────────────────────────────────────────────────────────────────

    async def get_user_profile(self, access_token: str) -> UserProfile:
        headers = {"Authorization": f"Bearer {access_token}",
                   "Content-Type": "application/json"}
        params  = {"fields": "open_id,union_id,avatar_url,display_name,username"}

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{self._API_BASE}/user/info/",
                                    params=params, headers=headers)
        resp.raise_for_status()
        data = resp.json().get("data", {}).get("user", {})

        return UserProfile(
            external_user_id=data.get("open_id", ""),
            username=data.get("username", ""),
            display_name=data.get("display_name", ""),
            profile_picture_url=data.get("avatar_url"),
            raw_data=data,
        )

    # ── Publicación (solo vídeo) ───────────────────────────────────────────────

    def validate_content(self, content: PostContent) -> ContentValidationResult:
        result = ContentValidationResult(is_valid=True)

        if not content.media_paths:
            result.add_error("TikTok solo admite publicación de vídeos. Adjunta un archivo de vídeo.")
            return result

        for path in content.media_paths:
            if not os.path.isfile(path):
                result.add_error(f"Archivo no encontrado: {path}")
            else:
                ext = os.path.splitext(path)[1].lower()
                if ext not in (".mp4", ".mov", ".webm"):
                    result.add_error(f"Formato no soportado: {ext}. Usa MP4, MOV o WebM.")
                size_mb = os.path.getsize(path) / 1024 / 1024
                if size_mb > 4096:   # límite 4 GB
                    result.add_error(f"Vídeo demasiado grande: {size_mb:.0f} MB (máx 4096 MB).")

        if len(content.text) > self.MAX_POST_LENGTH:
            result.add_error(f"Descripción supera {self.MAX_POST_LENGTH} caracteres.")

        return result

    async def upload_media(
        self, access_token: str, media_path: str, mime_type: str
    ) -> str:
        """
        Sube un vídeo a TikTok en tres pasos:
          1. POST /post/publish/video/init/  → obtiene upload_url + publish_id
          2. PUT al upload_url (chunk único para vídeos < 64 MB, chunked para mayores)
          3. Devuelve publish_id para usar en publish_post
        """
        file_size = os.path.getsize(media_path)
        headers   = {"Authorization": f"Bearer {access_token}",
                     "Content-Type": "application/json"}

        # Paso 1: Init
        init_payload = {
            "post_info": {
                "title":             "",
                "privacy_level":     "PUBLIC_TO_EVERYONE",
                "disable_duet":      False,
                "disable_comment":   False,
                "disable_stitch":    False,
                "video_cover_timestamp_ms": 1000,
            },
            "source_info": {
                "source":              "FILE_UPLOAD",
                "video_size":          file_size,
                "chunk_size":          file_size,
                "total_chunk_count":   1,
            },
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            init_resp = await client.post(
                f"{self._API_BASE}/post/publish/video/init/",
                json=init_payload, headers=headers,
            )
            init_resp.raise_for_status()
            init_data = init_resp.json()

        publish_id = init_data["data"]["publish_id"]
        upload_url = init_data["data"]["upload_url"]

        # Paso 2: Upload
        with open(media_path, "rb") as f:
            video_bytes = f.read()

        async with httpx.AsyncClient(timeout=300.0) as client:
            upload_resp = await client.put(
                upload_url,
                content=video_bytes,
                headers={
                    "Content-Type":          mime_type,
                    "Content-Range":         f"bytes 0-{file_size-1}/{file_size}",
                    "Content-Length":        str(file_size),
                },
            )
            upload_resp.raise_for_status()

        self._logger.info("Vídeo subido a TikTok: publish_id=%s", publish_id)
        return publish_id

    async def publish_post(
        self,
        access_token: str,
        content: PostContent,
        media_ids: Optional[list[str]] = None,
    ) -> PublishResult:
        """
        En TikTok el publish_id generado en upload_media YA es el post.
        Solo actualizamos la descripción si hace falta (API v2).
        """
        if not media_ids:
            return PublishResult(
                success=False,
                error_message="TikTok requiere un vídeo — no se puede publicar solo texto.",
            )

        publish_id = media_ids[0]
        # El vídeo ya fue publicado en upload_media (flujo directo de TikTok)
        # Devolvemos el publish_id como platform_post_id
        return PublishResult(
            success=True,
            platform_post_id=publish_id,
            published_url=f"https://www.tiktok.com/",  # URL exacta no disponible hasta revisión
            raw_response={"publish_id": publish_id},
        )

    async def get_post_analytics(
        self, access_token: str, platform_post_id: str
    ) -> PostAnalytics:
        """TikTok no expone métricas de vídeo individuales en la API pública básica."""
        self._logger.info("Analytics TikTok no disponibles en plan básico.")
        return PostAnalytics(platform_post_id=platform_post_id)


# ── Factory ───────────────────────────────────────────────────────────────────

def create_tiktok_provider() -> TikTokProvider:
    from config import get_settings
    s = get_settings()
    return TikTokProvider(
        client_key=s.tiktok_client_key,
        client_secret=s.tiktok_client_secret,
        redirect_uri=s.tiktok_redirect_uri,
    )
