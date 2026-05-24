"""
providers/x_twitter.py — Provider X / Twitter (Fase 2)

Implementa OAuth2 con PKCE (Authorization Code Flow + PKCE).
API v2 de X/Twitter.

Endpoints:
  Auth:    https://twitter.com/i/oauth2/authorize
  Token:   https://api.twitter.com/2/oauth2/token
  Revoke:  https://api.twitter.com/2/oauth2/revoke
  Me:      https://api.twitter.com/2/users/me
  Tweet:   https://api.twitter.com/2/tweets

Scopes necesarios (portal developer.twitter.com):
  tweet.read tweet.write users.read offline.access

Nota sobre PKCE:
  X requiere PKCE obligatorio para OAuth2. Genera code_verifier aleatorio,
  lo hashea (SHA256) y envía el code_challenge en la URL de autorización.
  El code_verifier se guarda en sesión y se envía en el token exchange.
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


class XTwitterProvider(SocialMediaProvider):
    """
    Conector X/Twitter. OAuth2 + PKCE. API v2.
    Límite de caracteres: 280 (cuenta libre) / 25.000 (Twitter Blue/X Premium).
    """

    PLATFORM_NAME    = "X / Twitter"
    MAX_POST_LENGTH  = 280
    SUPPORTED_MIME_TYPES = [
        "image/jpeg", "image/png", "image/gif", "image/webp",
        "video/mp4",
    ]

    _AUTH_URL    = "https://twitter.com/i/oauth2/authorize"
    _TOKEN_URL   = "https://api.twitter.com/2/oauth2/token"
    _REVOKE_URL  = "https://api.twitter.com/2/oauth2/revoke"
    _API_BASE    = "https://api.twitter.com/2"
    _UPLOAD_URL  = "https://upload.twitter.com/1.1/media/upload.json"

    # Almacén de code_verifiers en memoria (platform → verifier)
    # En producción usar sesiones firmadas o Redis
    _pkce_store: dict[str, str] = {}

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        scopes: Optional[list[str]] = None,
    ) -> None:
        super().__init__(client_id, client_secret, redirect_uri)
        self._scopes = scopes or [
            "tweet.read", "tweet.write", "users.read", "offline.access"
        ]

    # ── PKCE helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _pkce_pair() -> tuple[str, str]:
        """Genera (code_verifier, code_challenge) para PKCE."""
        verifier  = secrets.token_urlsafe(64)
        digest    = hashlib.sha256(verifier.encode()).digest()
        challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
        return verifier, challenge

    # ── OAuth2 PKCE ───────────────────────────────────────────────────────────

    def get_authorization_url(self) -> tuple[str, str]:
        state    = self._generate_state()
        verifier, challenge = self._pkce_pair()

        # Guardar verifier ligado al state
        XTwitterProvider._pkce_store[state] = verifier

        params = {
            "response_type":         "code",
            "client_id":             self._client_id,
            "redirect_uri":          self._redirect_uri,
            "scope":                 " ".join(self._scopes),
            "state":                 state,
            "code_challenge":        challenge,
            "code_challenge_method": "S256",
        }
        url = f"{self._AUTH_URL}?{urlencode(params)}"
        self._logger.info("URL de autorización X generada (state=%s...)", state[:8])
        return url, state

    async def handle_callback(
        self, code: str, state: str, expected_state: str
    ) -> OAuthTokens:
        self._validate_state_or_raise(state, expected_state)

        verifier = XTwitterProvider._pkce_store.pop(state, None)
        if not verifier:
            raise ValueError("code_verifier no encontrado para este state.")

        # Basic auth: client_id:client_secret en Base64
        credentials = base64.b64encode(
            f"{self._client_id}:{self._client_secret}".encode()
        ).decode()

        payload = {
            "grant_type":    "authorization_code",
            "code":          code,
            "redirect_uri":  self._redirect_uri,
            "code_verifier": verifier,
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                self._TOKEN_URL,
                data=payload,
                headers={
                    "Content-Type":  "application/x-www-form-urlencoded",
                    "Authorization": f"Basic {credentials}",
                },
            )

        if response.status_code != 200:
            raise PermissionError(
                f"X rechazó el intercambio de tokens: {response.text}"
            )

        data: dict[str, Any] = response.json()
        if "error" in data:
            raise PermissionError(
                f"X OAuth error: {data.get('error')} — {data.get('error_description')}"
            )

        return OAuthTokens(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_in_seconds=data.get("expires_in"),
            scopes=data.get("scope", "").split() if data.get("scope") else self._scopes,
            raw_response=data,
        )

    async def refresh_access_token(self, refresh_token: str) -> OAuthTokens:
        credentials = base64.b64encode(
            f"{self._client_id}:{self._client_secret}".encode()
        ).decode()

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                self._TOKEN_URL,
                data={
                    "grant_type":    "refresh_token",
                    "refresh_token": refresh_token,
                },
                headers={
                    "Content-Type":  "application/x-www-form-urlencoded",
                    "Authorization": f"Basic {credentials}",
                },
            )

        response.raise_for_status()
        data = response.json()
        return OAuthTokens(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token", refresh_token),
            expires_in_seconds=data.get("expires_in"),
            raw_response=data,
        )

    async def revoke_token(self, access_token: str) -> bool:
        credentials = base64.b64encode(
            f"{self._client_id}:{self._client_secret}".encode()
        ).decode()

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                self._REVOKE_URL,
                data={"token": access_token, "token_type_hint": "access_token"},
                headers={
                    "Content-Type":  "application/x-www-form-urlencoded",
                    "Authorization": f"Basic {credentials}",
                },
            )
        return response.status_code == 200

    # ── Perfil ────────────────────────────────────────────────────────────────

    async def get_user_profile(self, access_token: str) -> UserProfile:
        params = {"user.fields": "id,name,username,profile_image_url"}
        headers = {"Authorization": f"Bearer {access_token}"}

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{self._API_BASE}/users/me",
                params=params,
                headers=headers,
            )

        response.raise_for_status()
        data = response.json().get("data", {})

        return UserProfile(
            external_user_id=data.get("id", ""),
            username=data.get("username", ""),
            display_name=data.get("name", ""),
            profile_picture_url=data.get("profile_image_url"),
            raw_data=data,
        )

    # ── Publicación ───────────────────────────────────────────────────────────

    def validate_content(self, content: PostContent) -> ContentValidationResult:
        result = ContentValidationResult(is_valid=True)
        text_len = len(content.full_text)

        if not content.text.strip():
            result.add_error("El tweet no puede estar vacío.")

        if text_len > self.MAX_POST_LENGTH:
            result.add_error(
                f"El tweet supera {self.MAX_POST_LENGTH} caracteres: {text_len}."
            )
        elif text_len > int(self.MAX_POST_LENGTH * 0.9):
            result.add_warning(
                f"El tweet ocupa el {text_len/self.MAX_POST_LENGTH:.0%} del límite."
            )

        if len(content.media_paths) > 4:
            result.add_error("X permite máximo 4 archivos de media por tweet.")

        for path in content.media_paths:
            if not os.path.isfile(path):
                result.add_error(f"Archivo no encontrado: {path}")

        return result

    async def upload_media(
        self, access_token: str, media_path: str, mime_type: str
    ) -> str:
        """
        Sube media usando la Twitter Media Upload API v1.1 (INIT → APPEND → FINALIZE).
        Devuelve el media_id_string para referenciar en el tweet.
        """
        with open(media_path, "rb") as f:
            media_bytes = f.read()

        total_bytes = len(media_bytes)
        headers = {"Authorization": f"Bearer {access_token}"}

        async with httpx.AsyncClient(timeout=60.0) as client:
            # INIT
            init_resp = await client.post(
                self._UPLOAD_URL,
                data={
                    "command":      "INIT",
                    "total_bytes":  total_bytes,
                    "media_type":   mime_type,
                },
                headers=headers,
            )
            init_resp.raise_for_status()
            media_id = init_resp.json()["media_id_string"]

            # APPEND (chunks de 5 MB)
            chunk_size = 5 * 1024 * 1024
            for i, offset in enumerate(range(0, total_bytes, chunk_size)):
                chunk = media_bytes[offset:offset + chunk_size]
                await client.post(
                    self._UPLOAD_URL,
                    data={"command": "APPEND", "media_id": media_id, "segment_index": i},
                    files={"media": chunk},
                    headers=headers,
                )

            # FINALIZE
            await client.post(
                self._UPLOAD_URL,
                data={"command": "FINALIZE", "media_id": media_id},
                headers=headers,
            )

        self._logger.info("Media subida a X: %s → media_id=%s", media_path, media_id)
        return media_id

    async def publish_post(
        self,
        access_token: str,
        content: PostContent,
        media_ids: Optional[list[str]] = None,
    ) -> PublishResult:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type":  "application/json",
        }

        payload: dict[str, Any] = {"text": content.full_text}
        if media_ids:
            payload["media"] = {"media_ids": media_ids}

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self._API_BASE}/tweets",
                json=payload,
                headers=headers,
            )

        if response.status_code in (200, 201):
            data = response.json()
            tweet_id = data.get("data", {}).get("id", "")
            username = ""
            try:
                profile = await self.get_user_profile(access_token)
                username = profile.username
            except Exception:
                pass
            tweet_url = f"https://x.com/{username}/status/{tweet_id}" if username else ""
            self._logger.info("Tweet publicado: id=%s", tweet_id)
            return PublishResult(
                success=True,
                platform_post_id=tweet_id,
                published_url=tweet_url,
                raw_response=data,
            )

        return PublishResult(
            success=False,
            error_message=f"X API error {response.status_code}: {response.text}",
        )

    async def get_post_analytics(
        self, access_token: str, platform_post_id: str
    ) -> PostAnalytics:
        """
        Métricas públicas del tweet.
        Requiere permisos de lectura de métricas (solo para cuentas verificadas
        con acceso Elevated o Basic en la API v2).
        """
        params = {
            "ids":          platform_post_id,
            "tweet.fields": "public_metrics",
        }
        headers = {"Authorization": f"Bearer {access_token}"}

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{self._API_BASE}/tweets",
                params=params,
                headers=headers,
            )

        if response.status_code != 200:
            return PostAnalytics(platform_post_id=platform_post_id)

        data  = response.json()
        tweet = data.get("data", [{}])[0] if data.get("data") else {}
        m     = tweet.get("public_metrics", {})

        return PostAnalytics(
            platform_post_id=platform_post_id,
            likes=m.get("like_count", 0),
            comments=m.get("reply_count", 0),
            shares=m.get("retweet_count", 0),
            impressions=m.get("impression_count", 0),
            reach=m.get("impression_count", 0),
        )


# ── Factory ───────────────────────────────────────────────────────────────────

def create_x_provider() -> XTwitterProvider:
    from config import get_settings
    s = get_settings()
    return XTwitterProvider(
        client_id=s.x_client_id,
        client_secret=s.x_client_secret,
        redirect_uri=s.x_redirect_uri,
    )
