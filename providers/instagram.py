"""
providers/instagram.py — Provider Instagram via Meta Graph API (Fase 4)

Publica en páginas de Instagram Business/Creator conectadas a una página de Facebook.
Requiere una app Meta con Instagram Graph API habilitado.

Flujo OAuth2:
  Auth:    https://www.facebook.com/v19.0/dialog/oauth
  Token:   https://graph.facebook.com/v19.0/oauth/access_token
  API:     https://graph.facebook.com/v19.0/

Pasos de publicación (Container Model):
  1. POST /{ig-user-id}/media          → crea el container (image_url/video_url + caption)
  2. POST /{ig-user-id}/media_publish  → publica el container
  3. GET  /{media-id}?fields=...       → obtiene métricas

Scopes necesarios:
  instagram_basic  instagram_content_publish  pages_read_engagement
  pages_show_list  business_management

Notas:
  • Solo funciona con cuentas Business o Creator.
  • Las imágenes deben ser URLs públicas (no archivos locales directos).
  • Para vídeos: se usa el endpoint de Reels (/reels).
  • El token de usuario de larga duración dura 60 días.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional
from urllib.parse import urlencode

import httpx

from providers.base import (
    ContentValidationResult, OAuthTokens, PostAnalytics,
    PostContent, PublishResult, SocialMediaProvider, UserProfile,
)

logger = logging.getLogger(__name__)

_API_VERSION = "v19.0"


class InstagramProvider(SocialMediaProvider):
    """Provider Instagram Business via Meta Graph API."""

    PLATFORM_NAME   = "Instagram"
    MAX_POST_LENGTH = 2200
    SUPPORTED_MIME_TYPES = [
        "image/jpeg", "image/png",
        "video/mp4", "video/quicktime",
    ]

    _AUTH_URL    = f"https://www.facebook.com/{_API_VERSION}/dialog/oauth"
    _TOKEN_URL   = f"https://graph.facebook.com/{_API_VERSION}/oauth/access_token"
    _LONG_TOKEN  = f"https://graph.facebook.com/{_API_VERSION}/oauth/access_token"
    _API_BASE    = f"https://graph.facebook.com/{_API_VERSION}"

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        redirect_uri: str,
        scopes: Optional[list[str]] = None,
    ) -> None:
        super().__init__(app_id, app_secret, redirect_uri)
        self._scopes = scopes or [
            "instagram_basic",
            "instagram_content_publish",
            "pages_read_engagement",
            "pages_show_list",
            "business_management",
        ]

    # ── OAuth2 ────────────────────────────────────────────────────────────────

    def get_authorization_url(self) -> tuple[str, str]:
        state  = self._generate_state()
        params = {
            "client_id":     self._client_id,
            "redirect_uri":  self._redirect_uri,
            "scope":         ",".join(self._scopes),
            "response_type": "code",
            "state":         state,
        }
        url = f"{self._AUTH_URL}?{urlencode(params)}"
        self._logger.info("URL autorización Instagram generada.")
        return url, state

    async def handle_callback(
        self, code: str, state: str, expected_state: str
    ) -> OAuthTokens:
        self._validate_state_or_raise(state, expected_state)

        # 1. Intercambiar code por short-lived token
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                self._TOKEN_URL,
                params={
                    "client_id":     self._client_id,
                    "client_secret": self._client_secret,
                    "redirect_uri":  self._redirect_uri,
                    "code":          code,
                },
            )
        resp.raise_for_status()
        data = resp.json()

        if "error" in data:
            raise PermissionError(
                f"Meta OAuth error: {data['error'].get('message', data['error'])}"
            )

        short_token = data["access_token"]

        # 2. Intercambiar por long-lived token (dura 60 días)
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp2 = await client.get(
                self._LONG_TOKEN,
                params={
                    "grant_type":        "fb_exchange_token",
                    "client_id":         self._client_id,
                    "client_secret":     self._client_secret,
                    "fb_exchange_token": short_token,
                },
            )
        resp2.raise_for_status()
        data2 = resp2.json()

        return OAuthTokens(
            access_token=data2.get("access_token", short_token),
            expires_in_seconds=data2.get("expires_in"),
            scopes=self._scopes,
            raw_response=data2,
        )

    async def refresh_access_token(self, refresh_token: str) -> OAuthTokens:
        """Meta no tiene refresh_token estándar — re-solicitar el long-lived token."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                self._LONG_TOKEN,
                params={
                    "grant_type":        "fb_exchange_token",
                    "client_id":         self._client_id,
                    "client_secret":     self._client_secret,
                    "fb_exchange_token": refresh_token,
                },
            )
        resp.raise_for_status()
        data = resp.json()
        return OAuthTokens(
            access_token=data["access_token"],
            expires_in_seconds=data.get("expires_in"),
            raw_response=data,
        )

    async def revoke_token(self, access_token: str) -> bool:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.delete(
                f"{self._API_BASE}/me/permissions",
                params={"access_token": access_token},
            )
        return resp.status_code == 200

    # ── Perfil ────────────────────────────────────────────────────────────────

    async def get_user_profile(self, access_token: str) -> UserProfile:
        """Obtiene el perfil de la cuenta de Instagram Business asociada."""
        # Primero obtenemos el usuario de Facebook
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Obtener páginas de Facebook
            pages_resp = await client.get(
                f"{self._API_BASE}/me/accounts",
                params={"access_token": access_token, "fields": "id,name,instagram_business_account"},
            )
        pages_resp.raise_for_status()
        pages = pages_resp.json().get("data", [])

        # Encontrar la cuenta de Instagram Business
        ig_account_id = None
        ig_name       = None
        fb_user_id    = None

        for page in pages:
            ig = page.get("instagram_business_account")
            if ig:
                ig_account_id = ig.get("id")
                ig_name       = page.get("name", "")
                fb_user_id    = page.get("id")
                break

        if not ig_account_id:
            # Fallback: usar perfil de FB
            async with httpx.AsyncClient(timeout=10.0) as client:
                me_resp = await client.get(
                    f"{self._API_BASE}/me",
                    params={"access_token": access_token, "fields": "id,name,picture"},
                )
            me_resp.raise_for_status()
            me = me_resp.json()
            return UserProfile(
                external_user_id=me.get("id", ""),
                display_name=me.get("name", ""),
                raw_data=me,
            )

        # Obtener detalles de la cuenta IG
        async with httpx.AsyncClient(timeout=10.0) as client:
            ig_resp = await client.get(
                f"{self._API_BASE}/{ig_account_id}",
                params={
                    "access_token": access_token,
                    "fields": "id,username,name,profile_picture_url,followers_count",
                },
            )
        ig_resp.raise_for_status()
        ig_data = ig_resp.json()

        return UserProfile(
            external_user_id=ig_account_id,
            username=ig_data.get("username", ""),
            display_name=ig_data.get("name", ig_name or ""),
            profile_picture_url=ig_data.get("profile_picture_url"),
            raw_data=ig_data,
        )

    # ── Publicación ───────────────────────────────────────────────────────────

    def validate_content(self, content: PostContent) -> ContentValidationResult:
        result = ContentValidationResult(is_valid=True)

        if not content.text.strip() and not content.media_paths:
            result.add_error("Instagram requiere al menos texto o una imagen/vídeo.")

        if len(content.full_text) > self.MAX_POST_LENGTH:
            result.add_error(
                f"Caption supera {self.MAX_POST_LENGTH} caracteres: {len(content.full_text)}."
            )

        if len(content.media_paths) > 10:
            result.add_error("Instagram permite máximo 10 imágenes por carrusel.")

        for path in content.media_paths:
            if not os.path.isfile(path):
                result.add_error(f"Archivo no encontrado: {path}")

        return result

    async def upload_media(
        self, access_token: str, media_path: str, mime_type: str
    ) -> str:
        """
        Instagram Graph API requiere URLs públicas para las imágenes.
        Para el PoC devolvemos el path — en producción habría que subir
        a un CDN o usar imgbb/cloudinary.
        """
        self._logger.warning(
            "Instagram requiere URLs públicas para media. "
            "Sube el archivo a un CDN y usa la URL en el post."
        )
        return media_path  # Placeholder — requiere CDN en producción

    async def _get_ig_user_id(self, access_token: str) -> str:
        """Obtiene el ig_user_id de la cuenta Business."""
        profile = await self.get_user_profile(access_token)
        return profile.external_user_id

    async def publish_post(
        self,
        access_token: str,
        content: PostContent,
        media_ids: Optional[list[str]] = None,  # URLs o paths de media
    ) -> PublishResult:
        """
        Publica usando el Container Model de Instagram:
          1. Crear container (media + caption)
          2. Publicar container
        """
        ig_user_id = await self._get_ig_user_id(access_token)
        caption    = content.full_text[:self.MAX_POST_LENGTH]
        media_urls = media_ids or []

        try:
            if not media_urls:
                # Solo texto — Instagram no permite posts sin imagen
                return PublishResult(
                    success=False,
                    error_message="Instagram no permite posts de solo texto. Adjunta al menos una imagen.",
                )

            if len(media_urls) == 1:
                container_id = await self._create_single_container(
                    access_token, ig_user_id, media_urls[0], caption
                )
            else:
                container_id = await self._create_carousel_container(
                    access_token, ig_user_id, media_urls, caption
                )

            # Publicar el container
            async with httpx.AsyncClient(timeout=30.0) as client:
                pub_resp = await client.post(
                    f"{self._API_BASE}/{ig_user_id}/media_publish",
                    params={
                        "creation_id": container_id,
                        "access_token": access_token,
                    },
                )
            pub_resp.raise_for_status()
            pub_data = pub_resp.json()

            media_id = pub_data.get("id", "")
            self._logger.info("Post Instagram publicado: media_id=%s", media_id)
            return PublishResult(
                success=True,
                platform_post_id=media_id,
                published_url=f"https://www.instagram.com/p/{media_id}/",
                raw_response=pub_data,
            )

        except Exception as exc:
            return PublishResult(success=False, error_message=str(exc))

    async def _create_single_container(
        self, access_token: str, ig_user_id: str, media_url: str, caption: str
    ) -> str:
        ext = os.path.splitext(media_url)[1].lower()
        is_video = ext in (".mp4", ".mov")

        params: dict[str, Any] = {
            "caption":      caption,
            "access_token": access_token,
        }
        if is_video:
            params["media_type"] = "REELS"
            params["video_url"]  = media_url
        else:
            params["image_url"] = media_url

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self._API_BASE}/{ig_user_id}/media",
                params=params,
            )
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"Instagram container error: {data['error']}")
        return data["id"]

    async def _create_carousel_container(
        self, access_token: str, ig_user_id: str, media_urls: list[str], caption: str
    ) -> str:
        """Crea los containers de cada imagen y luego el container del carrusel."""
        child_ids = []
        for url in media_urls:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{self._API_BASE}/{ig_user_id}/media",
                    params={"image_url": url, "is_carousel_item": True,
                            "access_token": access_token},
                )
            resp.raise_for_status()
            child_ids.append(resp.json()["id"])

        async with httpx.AsyncClient(timeout=30.0) as client:
            carousel_resp = await client.post(
                f"{self._API_BASE}/{ig_user_id}/media",
                params={
                    "media_type":  "CAROUSEL",
                    "children":    ",".join(child_ids),
                    "caption":     caption,
                    "access_token": access_token,
                },
            )
        carousel_resp.raise_for_status()
        return carousel_resp.json()["id"]

    # ── Analytics ─────────────────────────────────────────────────────────────

    async def get_post_analytics(
        self, access_token: str, platform_post_id: str
    ) -> PostAnalytics:
        fields = "like_count,comments_count,impressions,reach,saved"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self._API_BASE}/{platform_post_id}/insights",
                params={
                    "metric":       fields,
                    "access_token": access_token,
                },
            )

        if resp.status_code != 200:
            return PostAnalytics(platform_post_id=platform_post_id)

        data    = resp.json()
        metrics = {item["name"]: item.get("values", [{}])[0].get("value", 0)
                   for item in data.get("data", [])}

        return PostAnalytics(
            platform_post_id=platform_post_id,
            likes=metrics.get("like_count", 0),
            comments=metrics.get("comments_count", 0),
            impressions=metrics.get("impressions", 0),
            reach=metrics.get("reach", 0),
        )


def create_instagram_provider() -> InstagramProvider:
    from config import get_settings
    s = get_settings()
    return InstagramProvider(
        app_id=s.meta_app_id,
        app_secret=s.meta_app_secret,
        redirect_uri=s.meta_redirect_uri,
    )
