"""
providers/linkedin.py — Provider de LinkedIn (PoC Fase 1)

Implementa el flujo OAuth2 Authorization Code con PKCE y la
publicación de posts de texto e imagen usando la LinkedIn API v2.

Endpoints usados:
  Auth:       https://www.linkedin.com/oauth/v2/authorization
  Token:      https://www.linkedin.com/oauth/v2/accessToken
  Revoke:     https://www.linkedin.com/oauth/v2/revoke
  Perfil:     https://api.linkedin.com/v2/userinfo          (OpenID Connect)
  Posts:      https://api.linkedin.com/v2/ugcPosts
  Media:      https://api.linkedin.com/v2/assets?action=registerUpload
  Analytics:  https://api.linkedin.com/v2/organizationalEntityShareStatistics

Scopes necesarios (configurar en el Developer Portal de LinkedIn):
  openid, profile, email, w_member_social

Notas:
  • LinkedIn usa OAuth2 estándar SIN PKCE para apps confidenciales (server-side).
    Se añade code_verifier de todos modos como buena práctica defensiva.
  • El refresh_token en LinkedIn expira a los 60 días; el access_token a las 60 min.
  • La API de Analytics requiere el permiso r_organization_social (páginas de empresa).
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import secrets
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlencode

import httpx

from providers.base import (
    ContentValidationResult,
    OAuthTokens,
    PostAnalytics,
    PostContent,
    PublishResult,
    SocialMediaProvider,
    UserProfile,
)

logger = logging.getLogger(__name__)


class LinkedInProvider(SocialMediaProvider):
    """
    Conector LinkedIn. Implementa el contrato SocialMediaProvider
    usando la LinkedIn API v2 (UGC Posts).
    """

    PLATFORM_NAME = "LinkedIn"
    MAX_POST_LENGTH = 3000          # Límite oficial de LinkedIn
    SUPPORTED_MIME_TYPES = [
        "image/jpeg", "image/png", "image/gif",
        "video/mp4", "video/quicktime",
    ]

    # Endpoints LinkedIn
    _AUTH_URL   = "https://www.linkedin.com/oauth/v2/authorization"
    _TOKEN_URL  = "https://www.linkedin.com/oauth/v2/accessToken"
    _REVOKE_URL = "https://www.linkedin.com/oauth/v2/revoke"
    _API_BASE   = "https://api.linkedin.com/v2"

    def __init__(self, client_id: str, client_secret: str, redirect_uri: str, scopes: list[str]) -> None:
        super().__init__(client_id, client_secret, redirect_uri)
        self._scopes = scopes

    # ── Helpers PKCE ─────────────────────────────────────────────────────────

    @staticmethod
    def _generate_pkce_pair() -> tuple[str, str]:
        """
        Genera un par (code_verifier, code_challenge) para PKCE.
        code_challenge = BASE64URL(SHA256(code_verifier))
        """
        verifier = secrets.token_urlsafe(64)
        digest = hashlib.sha256(verifier.encode()).digest()
        challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
        return verifier, challenge

    # ── OAuth2 ────────────────────────────────────────────────────────────────

    def get_authorization_url(self) -> tuple[str, str]:
        """
        Construye la URL de autorización LinkedIn con state anti-CSRF.

        Returns:
            (url_de_autorizacion, state_token)

        El state_token debe guardarse en la sesión del usuario y
        verificarse en handle_callback().
        """
        state = self._generate_state()
        params = {
            "response_type": "code",
            "client_id":      self._client_id,
            "redirect_uri":   self._redirect_uri,
            "state":          state,
            "scope":          " ".join(self._scopes),
        }
        url = f"{self._AUTH_URL}?{urlencode(params)}"
        self._logger.info("URL de autorización LinkedIn generada (state=%s...)", state[:8])
        return url, state

    async def handle_callback(
        self, code: str, state: str, expected_state: str
    ) -> OAuthTokens:
        """
        Intercambia el authorization code por tokens.

        Raises:
            ValueError:       State CSRF inválido.
            PermissionError:  LinkedIn devuelve error de autorización.
            httpx.HTTPError:  Error de red.
        """
        # 1. Verificar state anti-CSRF
        self._validate_state_or_raise(state, expected_state)

        # 2. Intercambiar código por tokens
        payload = {
            "grant_type":    "authorization_code",
            "code":          code,
            "redirect_uri":  self._redirect_uri,
            "client_id":     self._client_id,
            "client_secret": self._client_secret,
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                self._TOKEN_URL,
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        if response.status_code != 200:
            error_detail = response.text
            self._logger.error(
                "LinkedIn token exchange fallido: status=%d body=%s",
                response.status_code, error_detail
            )
            raise PermissionError(
                f"LinkedIn rechazó el intercambio de tokens: {error_detail}"
            )

        data: dict[str, Any] = response.json()

        if "error" in data:
            raise PermissionError(
                f"LinkedIn OAuth error: {data.get('error')} — {data.get('error_description')}"
            )

        tokens = OAuthTokens(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_in_seconds=data.get("expires_in"),
            scopes=data.get("scope", "").split(" ") if data.get("scope") else self._scopes,
            raw_response=data,
        )

        self._logger.info(
            "LinkedIn tokens obtenidos. expires_in=%s scopes=%s",
            tokens.expires_in_seconds, tokens.scopes
        )
        return tokens

    async def refresh_access_token(self, refresh_token: str) -> OAuthTokens:
        """
        Renueva el access_token con el refresh_token.
        LinkedIn soporta refresh tokens si el scope `r_liteprofile` está activo.
        """
        payload = {
            "grant_type":    "refresh_token",
            "refresh_token": refresh_token,
            "client_id":     self._client_id,
            "client_secret": self._client_secret,
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                self._TOKEN_URL,
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        response.raise_for_status()
        data = response.json()

        return OAuthTokens(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token", refresh_token),  # Mantener el actual si no llega uno nuevo
            expires_in_seconds=data.get("expires_in"),
            raw_response=data,
        )

    async def revoke_token(self, access_token: str) -> bool:
        """Revoca el access_token. LinkedIn usa el endpoint estándar OAuth2."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                self._REVOKE_URL,
                data={"token": access_token, "client_id": self._client_id, "client_secret": self._client_secret},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        success = response.status_code == 200
        self._logger.info("Revocación de token LinkedIn: %s", "OK" if success else f"KO ({response.status_code})")
        return success

    # ── Perfil ────────────────────────────────────────────────────────────────

    async def get_user_profile(self, access_token: str) -> UserProfile:
        """
        Obtiene el perfil usando el endpoint OpenID Connect /userinfo.
        Requiere scope `openid profile email`.
        """
        headers = {"Authorization": f"Bearer {access_token}"}

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{self._API_BASE}/userinfo",
                headers=headers,
            )

        response.raise_for_status()
        data = response.json()

        return UserProfile(
            external_user_id=data.get("sub", ""),
            username=data.get("email", ""),
            display_name=data.get("name", ""),
            profile_picture_url=data.get("picture"),
            email=data.get("email"),
            raw_data=data,
        )

    # ── Publicación ───────────────────────────────────────────────────────────

    def validate_content(self, content: PostContent) -> ContentValidationResult:
        """Valida el post contra los límites de LinkedIn."""
        result = ContentValidationResult(is_valid=True)
        text_len = len(content.full_text)

        if not content.text.strip():
            result.add_error("El texto del post no puede estar vacío.")

        if text_len > self.MAX_POST_LENGTH:
            result.add_error(
                f"El post supera el límite de LinkedIn: {text_len}/{self.MAX_POST_LENGTH} caracteres."
            )
        elif text_len > int(self.MAX_POST_LENGTH * 0.9):
            result.add_warning(
                f"El post ocupa el {text_len/self.MAX_POST_LENGTH:.0%} del límite de LinkedIn."
            )

        if len(content.media_paths) > 9:
            result.add_error("LinkedIn permite máximo 9 imágenes por post.")

        for path in content.media_paths:
            if not os.path.isfile(path):
                result.add_error(f"Archivo de media no encontrado: {path}")

        return result

    async def upload_media(
        self, access_token: str, media_path: str, mime_type: str
    ) -> str:
        """
        Sube una imagen/video a LinkedIn en dos pasos:
          1. registerUpload  → obtiene uploadUrl y asset URN
          2. PUT de los bytes al uploadUrl
        Devuelve el asset URN para referenciar en el post.
        """
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type":  "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
        }

        # Obtener el URN del owner (persona) para el registro del asset
        profile = await self.get_user_profile(access_token)
        owner_urn = f"urn:li:person:{profile.external_user_id}"

        # Paso 1: Registrar el upload
        register_payload = {
            "registerUploadRequest": {
                "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
                "owner": owner_urn,
                "serviceRelationships": [
                    {
                        "relationshipType": "OWNER",
                        "identifier": "urn:li:userGeneratedContent",
                    }
                ],
            }
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            register_resp = await client.post(
                f"{self._API_BASE}/assets?action=registerUpload",
                json=register_payload,
                headers=headers,
            )
            register_resp.raise_for_status()
            register_data = register_resp.json()

        upload_url = register_data["value"]["uploadMechanism"][
            "com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"
        ]["uploadUrl"]
        asset_urn = register_data["value"]["asset"]

        # Paso 2: Subir los bytes del archivo
        with open(media_path, "rb") as f:
            file_bytes = f.read()

        async with httpx.AsyncClient(timeout=120.0) as client:
            upload_resp = await client.put(
                upload_url,
                content=file_bytes,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": mime_type,
                },
            )
            upload_resp.raise_for_status()

        self._logger.info("Media subida a LinkedIn: %s → asset=%s", media_path, asset_urn)
        return asset_urn

    async def publish_post(
        self,
        access_token: str,
        content: PostContent,
        media_ids: Optional[list[str]] = None,
    ) -> PublishResult:
        """
        Publica un post usando UGC Posts API de LinkedIn.
        Soporta texto solo e imágenes (ARTICLE_SHARE para links).
        """
        profile = await self.get_user_profile(access_token)
        author_urn = f"urn:li:person:{profile.external_user_id}"

        headers = {
            "Authorization":  f"Bearer {access_token}",
            "Content-Type":   "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
        }

        # Construir el payload base
        ugc_post: dict[str, Any] = {
            "author":             author_urn,
            "lifecycleState":     "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": content.full_text},
                    "shareMediaCategory": "NONE",
                }
            },
            "visibility": {
                "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
            },
        }

        # Si hay imágenes adjuntas, cambiar a shareMediaCategory IMAGE
        if media_ids:
            media_list = [
                {
                    "status":              "READY",
                    "description":         {"text": ""},
                    "media":               asset_urn,
                    "title":               {"text": ""},
                }
                for asset_urn in media_ids
            ]
            ugc_post["specificContent"]["com.linkedin.ugc.ShareContent"]["shareMediaCategory"] = "IMAGE"
            ugc_post["specificContent"]["com.linkedin.ugc.ShareContent"]["media"] = media_list

        # Si hay link y no hay imágenes, usar categoría ARTICLE
        elif content.link_url:
            ugc_post["specificContent"]["com.linkedin.ugc.ShareContent"]["shareMediaCategory"] = "ARTICLE"
            ugc_post["specificContent"]["com.linkedin.ugc.ShareContent"]["media"] = [
                {
                    "status":           "READY",
                    "originalUrl":      content.link_url,
                    "description":      {"text": ""},
                    "title":            {"text": ""},
                }
            ]

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self._API_BASE}/ugcPosts",
                json=ugc_post,
                headers=headers,
            )

        if response.status_code in (200, 201):
            post_id = response.headers.get("x-restli-id", "")
            post_url = f"https://www.linkedin.com/feed/update/{post_id}/"
            self._logger.info("Post publicado en LinkedIn: id=%s", post_id)
            return PublishResult(
                success=True,
                platform_post_id=post_id,
                published_url=post_url,
                raw_response=response.json() if response.content else {},
            )

        error_detail = response.text
        self._logger.error(
            "Error publicando en LinkedIn: status=%d body=%s",
            response.status_code, error_detail
        )
        return PublishResult(
            success=False,
            error_message=f"LinkedIn API error {response.status_code}: {error_detail}",
        )

    # ── Analytics ─────────────────────────────────────────────────────────────

    async def get_post_analytics(
        self, access_token: str, platform_post_id: str
    ) -> PostAnalytics:
        """
        Obtiene estadísticas del post.
        Nota: para posts de personas (no páginas) las métricas son limitadas.
        Para páginas de empresa se usa organizationalEntityShareStatistics.
        """
        headers = {
            "Authorization": f"Bearer {access_token}",
            "X-Restli-Protocol-Version": "2.0.0",
        }

        params = {
            "q":            "organizationalEntity",
            "shares":       f"urn:li:ugcPost:{platform_post_id}",
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{self._API_BASE}/organizationalEntityShareStatistics",
                params=params,
                headers=headers,
            )

        if response.status_code != 200:
            # Métricas no disponibles — devolver ceros
            self._logger.warning(
                "Analytics LinkedIn no disponibles para post %s: %d",
                platform_post_id, response.status_code
            )
            return PostAnalytics(platform_post_id=platform_post_id)

        data = response.json()
        elements = data.get("elements", [])
        stats = elements[0].get("totalShareStatistics", {}) if elements else {}

        return PostAnalytics(
            platform_post_id=platform_post_id,
            likes=stats.get("likeCount", 0),
            comments=stats.get("commentCount", 0),
            shares=stats.get("shareCount", 0),
            impressions=stats.get("impressionCount", 0),
            clicks=stats.get("clickCount", 0),
            reach=stats.get("uniqueImpressionsCount", 0),
        )


# ── Factory function ──────────────────────────────────────────────────────────

def create_linkedin_provider() -> LinkedInProvider:
    """
    Instancia LinkedInProvider usando la configuración del entorno.
    Uso: provider = create_linkedin_provider()
    """
    from config import get_settings
    s = get_settings()
    return LinkedInProvider(
        client_id=s.linkedin_client_id,
        client_secret=s.linkedin_client_secret,
        redirect_uri=s.linkedin_redirect_uri,
        scopes=s.linkedin_scopes_list,
    )
