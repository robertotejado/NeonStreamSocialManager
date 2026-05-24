"""
models/database.py — Modelos SQLAlchemy + lógica de cifrado integrada

Tablas:
  • social_credentials  → tokens OAuth2 cifrados por red social
  • scheduled_posts     → posts programados con estado de ciclo de vida
  • post_media          → archivos adjuntos a posts
  • audit_log           → trazabilidad de operaciones sensibles

Cifrado:
  Los campos *_token y *_secret usan TypeDecorator (EncryptedString) que
  cifra automáticamente en INSERT/UPDATE y descifra en SELECT.
  La clave nunca toca la base de datos.
"""
from __future__ import annotations

import enum
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean, Column, DateTime, Enum, ForeignKey,
    Integer, LargeBinary, String, Text, UniqueConstraint, event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, Session
from sqlalchemy.types import TypeDecorator

from services.crypto import get_crypto

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  Type Decorator — cifrado transparente en columnas ORM
# ══════════════════════════════════════════════════════════════════════════════

class EncryptedString(TypeDecorator):
    """
    Almacena texto cifrado (Fernet) como BLOB en SQLite.

    • process_bind_param   → cifra antes de INSERT/UPDATE
    • process_result_value → descifra después de SELECT

    El campo Python siempre es str (o None).
    El campo SQLite siempre es bytes (o NULL).
    """
    impl = LargeBinary
    cache_ok = True

    def process_bind_param(self, value: Optional[str], dialect) -> Optional[bytes]:
        if value is None:
            return None
        return get_crypto().encrypt(value)

    def process_result_value(self, value: Optional[bytes], dialect) -> Optional[str]:
        if value is None:
            return None
        return get_crypto().decrypt(value)


# ══════════════════════════════════════════════════════════════════════════════
#  Enums
# ══════════════════════════════════════════════════════════════════════════════

class SocialPlatform(str, enum.Enum):
    LINKEDIN  = "linkedin"
    X_TWITTER = "x_twitter"
    INSTAGRAM = "instagram"
    FACEBOOK  = "facebook"
    TIKTOK    = "tiktok"
    TELEGRAM  = "telegram"


class PostStatus(str, enum.Enum):
    DRAFT      = "draft"        # Borrador, no programado
    SCHEDULED  = "scheduled"    # En cola del scheduler
    PUBLISHING = "publishing"   # En proceso de publicación (lock optimista)
    PUBLISHED  = "published"    # Publicado con éxito
    FAILED     = "failed"       # Error en la publicación
    CANCELLED  = "cancelled"    # Cancelado por el usuario


class AuditAction(str, enum.Enum):
    TOKEN_STORED   = "token_stored"
    TOKEN_REFRESHED = "token_refreshed"
    TOKEN_REVOKED  = "token_revoked"
    POST_CREATED   = "post_created"
    POST_PUBLISHED = "post_published"
    POST_FAILED    = "post_failed"
    AUTH_INITIATED = "auth_initiated"
    AUTH_COMPLETED = "auth_completed"


# ══════════════════════════════════════════════════════════════════════════════
#  Base declarativa
# ══════════════════════════════════════════════════════════════════════════════

class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ══════════════════════════════════════════════════════════════════════════════
#  Tabla: social_credentials
# ══════════════════════════════════════════════════════════════════════════════

class SocialCredential(Base):
    """
    Almacena las credenciales OAuth2 de cada red social conectada.

    Campos cifrados con Fernet (AES-128-CBC + HMAC-SHA256):
      • access_token
      • refresh_token
      • token_secret (OAuth1 — X legacy)

    Campos en claro (no sensibles):
      • platform, user_id externo, username, scopes, fechas de expiración.

    Restricción UNIQUE: (platform, external_user_id) → una sola cuenta
    por red social. Si el usuario reconecta, se hace UPDATE, no INSERT.
    """
    __tablename__ = "social_credentials"
    __table_args__ = (
        UniqueConstraint("platform", "external_user_id", name="uq_platform_user"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Identidad
    platform: Mapped[str] = mapped_column(
        Enum(SocialPlatform, native_enum=False), nullable=False, index=True
    )
    external_user_id: Mapped[str] = mapped_column(String(256), nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    profile_picture_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Tokens cifrados — TypeDecorator gestiona cifrado/descifrado automáticamente
    access_token: Mapped[Optional[str]] = mapped_column(EncryptedString, nullable=True)
    refresh_token: Mapped[Optional[str]] = mapped_column(EncryptedString, nullable=True)
    token_secret: Mapped[Optional[str]] = mapped_column(EncryptedString, nullable=True)  # OAuth1

    # Metadata del token (en claro — no sensibles)
    scopes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    # Relaciones
    posts: Mapped[list["ScheduledPost"]] = relationship(
        "ScheduledPost", back_populates="credential", cascade="all, delete-orphan"
    )

    def is_token_expired(self) -> bool:
        if self.token_expires_at is None:
            return False
        return datetime.now(timezone.utc) >= self.token_expires_at

    def __repr__(self) -> str:
        return f"<SocialCredential platform={self.platform} user={self.username}>"


# ══════════════════════════════════════════════════════════════════════════════
#  Tabla: scheduled_posts
# ══════════════════════════════════════════════════════════════════════════════

class ScheduledPost(Base):
    """
    Post programado para publicación en una red social.

    El campo `platform_post_id` se rellena tras la publicación exitosa
    con el ID que devuelve la API de la red social.
    """
    __tablename__ = "scheduled_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    credential_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("social_credentials.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform: Mapped[str] = mapped_column(
        Enum(SocialPlatform, native_enum=False), nullable=False, index=True
    )

    # Contenido
    content: Mapped[str] = mapped_column(Text, nullable=False)
    hashtags: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON array string
    link_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Programación
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(
        Enum(PostStatus, native_enum=False),
        default=PostStatus.DRAFT,
        nullable=False,
        index=True,
    )
    scheduler_job_id: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)

    # Resultado de publicación
    platform_post_id: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Metadata IA
    ai_generated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sentiment_score: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)  # pos/neg/neu

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    # Relaciones
    credential: Mapped["SocialCredential"] = relationship("SocialCredential", back_populates="posts")
    media_files: Mapped[list["PostMedia"]] = relationship(
        "PostMedia", back_populates="post", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        preview = self.content[:40].replace("\n", " ")
        return f"<ScheduledPost id={self.id} status={self.status} platform={self.platform} content='{preview}...'>"


# ══════════════════════════════════════════════════════════════════════════════
#  Tabla: post_media
# ══════════════════════════════════════════════════════════════════════════════

class PostMedia(Base):
    """Archivos multimedia adjuntos a un post programado."""
    __tablename__ = "post_media"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("scheduled_posts.id", ondelete="CASCADE"), nullable=False, index=True
    )

    file_path: Mapped[str] = mapped_column(Text, nullable=False)         # ruta local
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)  # image/jpeg, video/mp4…
    file_size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    platform_media_id: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)  # ID tras upload

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    post: Mapped["ScheduledPost"] = relationship("ScheduledPost", back_populates="media_files")

    def __repr__(self) -> str:
        return f"<PostMedia id={self.id} mime={self.mime_type} path={self.file_path}>"


# ══════════════════════════════════════════════════════════════════════════════
#  Tabla: audit_log
# ══════════════════════════════════════════════════════════════════════════════

class AuditLog(Base):
    """
    Registro inmutable de operaciones sensibles.

    Política: solo INSERT, nunca UPDATE ni DELETE.
    En producción considera una tabla append-only o un WORM store.
    """
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    action: Mapped[str] = mapped_column(
        Enum(AuditAction, native_enum=False), nullable=False, index=True
    )
    platform: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    entity_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # FK lógica (no FK real)
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)        # JSON extra
    ip_address: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False, index=True)

    def __repr__(self) -> str:
        return f"<AuditLog action={self.action} platform={self.platform} at={self.created_at}>"


# ══════════════════════════════════════════════════════════════════════════════
#  Bootstrap de la base de datos
# ══════════════════════════════════════════════════════════════════════════════

def get_engine():
    """Crea el engine SQLAlchemy a partir de la configuración."""
    from sqlalchemy import create_engine
    from config import get_settings

    settings = get_settings()
    connect_args = {}
    if settings.database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    return create_engine(
        settings.database_url,
        connect_args=connect_args,
        echo=False,  # Usar APP_DEBUG=true solo activa logs de NeonStream, no de SQLAlchemy
    )


def get_session_factory():
    """Devuelve una sessionmaker ligada al engine."""
    from sqlalchemy.orm import sessionmaker
    return sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)


def init_db() -> None:
    """Crea todas las tablas si no existen (idempotente)."""
    engine = get_engine()
    Base.metadata.create_all(engine)
    logger.info("Base de datos inicializada: %s", engine.url)


def get_db_session() -> Session:
    """
    Generador de sesiones para inyección de dependencias en FastAPI.

    Uso en rutas:
        @app.get("/example")
        def my_route(db: Session = Depends(get_db_session)):
            ...
    """
    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
