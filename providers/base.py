"""
providers/base.py — Clase base abstracta SocialMediaProvider

Define el contrato que TODOS los providers deben implementar.
Patrón: Strategy + Template Method.

Cada red social (LinkedIn, X, Instagram…) hereda de esta clase e
implementa los métodos abstractos. El scheduler y las rutas solo
conocen esta interfaz, nunca el provider concreto.

Jerarquía:
    SocialMediaProvider  (ABC)
        ├── LinkedInProvider
        ├── XTwitterProvider
        ├── InstagramProvider
        └── TikTokProvider

Ciclo de vida OAuth2 (Authorization Code Flow):
    1. get_authorization_url()  → redirige al usuario
    2. handle_callback()        → intercambia code por tokens → los cifra y guarda
    3. refresh_access_token()   → renueva cuando expira
    4. revoke_token()           → desconectar cuenta

Ciclo de vida de publicación:
    1. validate_content()       → comprueba límites de la plataforma
    2. upload_media()           → sube archivos antes del post (si aplica)
    3. publish_post()           → publica el contenido
    4. get_post_analytics()     → métricas post-publicación
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  DTOs (Data Transfer Objects) compartidos
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class OAuthTokens:
    """Resultado de un intercambio OAuth2 exitoso."""
    access_token: str
    refresh_token: Optional[str] = None
    token_secret: Optional[str] = None          # OAuth1 (X legacy)
    expires_in_seconds: Optional[int] = None
    scopes: Optional[list[str]] = None
    raw_response: dict[str, Any] = field(default_factory=dict)

    @property
    def expires_at(self) -> Optional[datetime]:
        if self.expires_in_seconds is None:
            return None
        from datetime import timedelta
        return datetime.now(timezone.utc) + timedelta(seconds=self.expires_in_seconds)


@dataclass
class UserProfile:
    """Perfil básico del usuario autenticado en la red social."""
    external_user_id: str
    username: Optional[str] = None
    display_name: Optional[str] = None
    profile_picture_url: Optional[str] = None
    email: Optional[str] = None
    raw_data: dict[str, Any] = field(default_factory=dict)


@dataclass
class PostContent:
    """Payload de un post listo para publicar."""
    text: str
    hashtags: list[str] = field(default_factory=list)
    link_url: Optional[str] = None
    media_paths: list[str] = field(default_factory=list)
    scheduled_post_id: Optional[int] = None  # FK al modelo DB

    @property
    def full_text(self) -> str:
        """Texto completo incluyendo hashtags al final."""
        tags = " ".join(f"#{h.lstrip('#')}" for h in self.hashtags)
        parts = [self.text]
        if self.link_url:
            parts.append(self.link_url)
        if tags:
            parts.append(tags)
        return "\n\n".join(filter(None, parts))


@dataclass
class PublishResult:
    """Resultado de una operación de publicación."""
    success: bool
    platform_post_id: Optional[str] = None
    published_url: Optional[str] = None
    error_message: Optional[str] = None
    raw_response: dict[str, Any] = field(default_factory=dict)


@dataclass
class PostAnalytics:
    """Métricas de un post publicado."""
    platform_post_id: str
    likes: int = 0
    comments: int = 0
    shares: int = 0
    impressions: int = 0
    clicks: int = 0
    reach: int = 0
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ContentValidationResult:
    """Resultado de validar un post contra los límites de la plataforma."""
    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)
        self.is_valid = False

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)


# ══════════════════════════════════════════════════════════════════════════════
#  Clase base abstracta
# ══════════════════════════════════════════════════════════════════════════════

class SocialMediaProvider(ABC):
    """
    Contrato abstracto para todos los conectores de redes sociales.

    Subclases DEBEN implementar los métodos marcados con @abstractmethod.
    Los métodos con implementación por defecto pueden sobreescribirse.
    """

    # Nombre legible de la plataforma (sobreescribir en cada subclase)
    PLATFORM_NAME: str = "Unknown"
    # Límite de caracteres del cuerpo del post
    MAX_POST_LENGTH: int = 3000
    # Tipos MIME soportados para media
    SUPPORTED_MIME_TYPES: list[str] = ["image/jpeg", "image/png"]

    def __init__(self, client_id: str, client_secret: str, redirect_uri: str) -> None:
        if not client_id or not client_secret:
            raise ValueError(
                f"{self.PLATFORM_NAME}: client_id y client_secret son obligatorios."
            )
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._logger = logging.getLogger(f"neonstream.providers.{self.PLATFORM_NAME.lower()}")

    # ── OAuth2: Authorization Code Flow ──────────────────────────────────────

    @abstractmethod
    def get_authorization_url(self) -> tuple[str, str]:
        """
        Genera la URL de autorización OAuth2 y un state anti-CSRF.

        Returns:
            Tupla (authorization_url, state_token).
            Guarda state_token en sesión para verificarlo en el callback.

        Ejemplo implementación:
            state = self._generate_state()
            url = f"{AUTH_URL}?client_id={self._client_id}&state={state}&..."
            return url, state
        """
        ...

    @abstractmethod
    async def handle_callback(self, code: str, state: str, expected_state: str) -> OAuthTokens:
        """
        Intercambia el authorization code por access_token + refresh_token.

        Args:
            code:           El código recibido en el query param del callback.
            state:          El state recibido en el callback.
            expected_state: El state guardado en sesión antes de redirigir.

        Returns:
            OAuthTokens con los tokens resultantes.

        Raises:
            ValueError:       Si el state no coincide (posible CSRF).
            PermissionError:  Si la API devuelve error de autorización.
            httpx.HTTPError:  Si falla la petición HTTP.
        """
        ...

    @abstractmethod
    async def refresh_access_token(self, refresh_token: str) -> OAuthTokens:
        """
        Renueva el access_token usando el refresh_token.

        Args:
            refresh_token: El refresh token almacenado cifrado en DB.

        Returns:
            Nuevos OAuthTokens. La subclase debe persistirlos en DB.
        """
        ...

    @abstractmethod
    async def revoke_token(self, access_token: str) -> bool:
        """
        Revoca el access_token (desconectar cuenta).

        Returns:
            True si la revocación fue exitosa.
        """
        ...

    @abstractmethod
    async def get_user_profile(self, access_token: str) -> UserProfile:
        """
        Obtiene el perfil del usuario autenticado.

        Args:
            access_token: Token de acceso válido.

        Returns:
            UserProfile con external_user_id, username, display_name…
        """
        ...

    # ── Publicación ───────────────────────────────────────────────────────────

    @abstractmethod
    def validate_content(self, content: PostContent) -> ContentValidationResult:
        """
        Valida el contenido del post contra los límites de la plataforma.
        Se llama ANTES de publicar para detectar errores sin consumir cuota API.

        Checks típicos: longitud de texto, tipos de media, número de imágenes.
        """
        ...

    @abstractmethod
    async def upload_media(
        self, access_token: str, media_path: str, mime_type: str
    ) -> str:
        """
        Sube un archivo multimedia y devuelve el ID de la plataforma.

        Algunas APIs (LinkedIn, Meta) requieren subir media antes del post.
        Si la plataforma no requiere pre-upload, implementar como no-op que
        devuelve el path original.

        Returns:
            ID de la media en la plataforma (para referenciar en publish_post).
        """
        ...

    @abstractmethod
    async def publish_post(
        self,
        access_token: str,
        content: PostContent,
        media_ids: Optional[list[str]] = None,
    ) -> PublishResult:
        """
        Publica el post en la red social.

        Args:
            access_token: Token válido.
            content:      Contenido a publicar.
            media_ids:    IDs de media ya subidos (resultado de upload_media).

        Returns:
            PublishResult con success, platform_post_id y published_url.
        """
        ...

    @abstractmethod
    async def get_post_analytics(
        self, access_token: str, platform_post_id: str
    ) -> PostAnalytics:
        """
        Obtiene las métricas de un post publicado.

        Args:
            access_token:     Token con permisos de analytics.
            platform_post_id: ID del post en la plataforma.
        """
        ...

    # ── Métodos opcionales (implementación por defecto) ───────────────────────

    async def get_inbox_mentions(
        self, access_token: str, since_timestamp: Optional[datetime] = None
    ) -> list[dict[str, Any]]:
        """
        Obtiene menciones y mensajes del inbox unificado.

        Por defecto devuelve lista vacía. Sobreescribir en providers que
        soporten esta funcionalidad.
        """
        self._logger.warning(
            "%s: get_inbox_mentions no implementado para esta plataforma.", self.PLATFORM_NAME
        )
        return []

    # ── Helpers de seguridad (disponibles para todas las subclases) ───────────

    @staticmethod
    def _generate_state(length: int = 32) -> str:
        """
        Genera un state token criptográficamente seguro para anti-CSRF.
        Usar en get_authorization_url() y verificar en handle_callback().
        """
        return secrets.token_urlsafe(length)

    @staticmethod
    def _verify_state(received: str, expected: str) -> bool:
        """
        Compara dos state tokens usando comparación en tiempo constante
        para prevenir timing attacks.
        """
        return hmac.compare_digest(received.encode(), expected.encode())

    def _validate_state_or_raise(self, received: str, expected: str) -> None:
        """Lanza ValueError si el state no coincide (posible CSRF)."""
        if not self._verify_state(received, expected):
            self._logger.warning(
                "State CSRF mismatch en callback de %s. received=%s expected=%s",
                self.PLATFORM_NAME, received[:8] + "...", expected[:8] + "..."
            )
            raise ValueError(
                f"State CSRF inválido en {self.PLATFORM_NAME}. "
                "La petición puede haber sido manipulada."
            )

    # ── Template Method: flujo completo de publicación ────────────────────────

    async def execute_publish_pipeline(
        self, access_token: str, content: PostContent
    ) -> PublishResult:
        """
        Template Method que orquesta el flujo completo de publicación:
          1. Valida contenido
          2. Sube media (si hay)
          3. Publica el post
          4. Devuelve resultado

        Las subclases NO deben sobreescribir este método; implementan
        los pasos individuales (validate_content, upload_media, publish_post).
        """
        self._logger.info(
            "Iniciando pipeline de publicación en %s (post_id=%s)",
            self.PLATFORM_NAME, content.scheduled_post_id
        )

        # Paso 1 — Validación
        validation = self.validate_content(content)
        if not validation.is_valid:
            error_msg = "; ".join(validation.errors)
            self._logger.error("Validación fallida: %s", error_msg)
            return PublishResult(success=False, error_message=error_msg)

        if validation.warnings:
            for w in validation.warnings:
                self._logger.warning("Advertencia de contenido: %s", w)

        # Paso 2 — Subida de media
        media_ids: list[str] = []
        for media_path in content.media_paths:
            try:
                import magic
                mime = magic.from_file(media_path, mime=True)
            except Exception:
                # Fallback si python-magic no está disponible
                ext = os.path.splitext(media_path)[1].lower()
                mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                        "gif": "image/gif", "mp4": "video/mp4"}.get(ext.lstrip("."), "application/octet-stream")

            try:
                media_id = await self.upload_media(access_token, media_path, mime)
                media_ids.append(media_id)
                self._logger.info("Media subida: %s → id=%s", media_path, media_id)
            except Exception as exc:
                self._logger.error("Error subiendo media %s: %s", media_path, exc)
                return PublishResult(success=False, error_message=f"Error subiendo media: {exc}")

        # Paso 3 — Publicación
        try:
            result = await self.publish_post(access_token, content, media_ids or None)
            if result.success:
                self._logger.info(
                    "Post publicado en %s con id=%s", self.PLATFORM_NAME, result.platform_post_id
                )
            else:
                self._logger.error("Publicación fallida: %s", result.error_message)
            return result
        except Exception as exc:
            self._logger.exception("Excepción no capturada en publish_post: %s", exc)
            return PublishResult(success=False, error_message=str(exc))

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} platform={self.PLATFORM_NAME}>"
