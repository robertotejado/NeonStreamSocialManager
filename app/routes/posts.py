"""
app/routes/posts.py — CRUD de posts programados + integración con APScheduler

Endpoints:
  POST   /posts/            → crear post (borrador o programado)
  GET    /posts/            → listar posts con filtros
  GET    /posts/{id}        → detalle de un post
  PATCH  /posts/{id}        → editar post (solo si está en DRAFT o SCHEDULED)
  DELETE /posts/{id}        → eliminar post y cancelar job
  POST   /posts/{id}/publish-now → publicar inmediatamente (sin esperar fecha)
  GET    /posts/scheduler/pending → listar jobs pendientes del scheduler
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from models.database import (
    AuditAction, AuditLog, PostStatus, ScheduledPost,
    SocialCredential, SocialPlatform, get_db_session,
)
from services.scheduler import cancel_post_job, list_pending_jobs, schedule_post

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Schemas Pydantic ──────────────────────────────────────────────────────────

class PostCreateRequest(BaseModel):
    credential_id: int       = Field(..., description="ID de la credencial OAuth2 a usar")
    platform:      str       = Field(..., description="linkedin | x_twitter | instagram…")
    content:       str       = Field(..., min_length=1, max_length=5000)
    hashtags:      list[str] = Field(default_factory=list)
    link_url:      Optional[str] = None
    scheduled_at:  Optional[datetime] = Field(
        None, description="ISO 8601 con timezone. Si se omite, se guarda como DRAFT."
    )
    ai_generated:  bool = False

    @field_validator("platform")
    @classmethod
    def validate_platform(cls, v: str) -> str:
        valid = {p.value for p in SocialPlatform}
        if v not in valid:
            raise ValueError(f"Plataforma '{v}' no soportada. Válidas: {valid}")
        return v

    @field_validator("scheduled_at")
    @classmethod
    def scheduled_must_be_future(cls, v: Optional[datetime]) -> Optional[datetime]:
        if v is None:
            return v
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        if v <= datetime.now(timezone.utc):
            raise ValueError("scheduled_at debe ser una fecha futura.")
        return v


class PostUpdateRequest(BaseModel):
    content:      Optional[str]      = Field(None, min_length=1, max_length=5000)
    hashtags:     Optional[list[str]] = None
    link_url:     Optional[str]      = None
    scheduled_at: Optional[datetime] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _post_to_dict(post: ScheduledPost) -> dict:
    hashtags = []
    if post.hashtags:
        try:
            hashtags = json.loads(post.hashtags)
        except Exception:
            hashtags = [h.strip() for h in post.hashtags.split(",") if h.strip()]

    return {
        "id":               post.id,
        "platform":         post.platform,
        "content":          post.content,
        "hashtags":         hashtags,
        "link_url":         post.link_url,
        "status":           post.status,
        "scheduled_at":     post.scheduled_at.isoformat() if post.scheduled_at else None,
        "published_at":     post.published_at.isoformat() if post.published_at else None,
        "platform_post_id": post.platform_post_id,
        "error_message":    post.error_message,
        "retry_count":      post.retry_count,
        "ai_generated":     post.ai_generated,
        "created_at":       post.created_at.isoformat(),
        "media_count":      len(post.media_files),
    }


# ══════════════════════════════════════════════════════════════════════════════
#  Endpoints
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/", summary="Crear post (borrador o programado)", status_code=201)
async def create_post(
    body: PostCreateRequest,
    db: Session = Depends(get_db_session),
):
    """
    Crea un nuevo post.
    - Si `scheduled_at` está presente → estado SCHEDULED y se registra en APScheduler.
    - Si no → estado DRAFT.
    """
    # Verificar que la credencial existe y está activa
    credential = db.query(SocialCredential).filter_by(
        id=body.credential_id,
        platform=body.platform,
        is_active=True,
    ).first()

    if not credential:
        raise HTTPException(
            status_code=404,
            detail=f"Credencial id={body.credential_id} no encontrada o inactiva para '{body.platform}'."
        )

    # Validar contenido pre-guardado usando el provider
    try:
        from providers.base import PostContent
        from services.scheduler import _get_provider_for_platform
        provider = _get_provider_for_platform(body.platform)
        content_obj = PostContent(text=body.content, hashtags=body.hashtags, link_url=body.link_url)
        validation = provider.validate_content(content_obj)
        if not validation.is_valid:
            raise HTTPException(status_code=422, detail={"validation_errors": validation.errors})
    except NotImplementedError:
        pass  # Provider no implementado aún — permitir guardar igualmente

    # Determinar estado inicial
    status = PostStatus.DRAFT
    if body.scheduled_at:
        status = PostStatus.SCHEDULED

    post = ScheduledPost(
        credential_id=body.credential_id,
        platform=body.platform,
        content=body.content,
        hashtags=json.dumps(body.hashtags) if body.hashtags else None,
        link_url=body.link_url,
        scheduled_at=body.scheduled_at,
        status=status,
        ai_generated=body.ai_generated,
    )
    db.add(post)
    db.flush()  # Para obtener post.id antes del commit

    # Registrar job en el scheduler si está programado
    if body.scheduled_at:
        job_id = schedule_post(post.id, body.scheduled_at)
        post.scheduler_job_id = job_id

    db.add(AuditLog(action=AuditAction.POST_CREATED, platform=body.platform, entity_id=post.id))
    db.commit()

    logger.info("Post id=%d creado. status=%s platform=%s", post.id, status, body.platform)
    return {"status": "created", "post": _post_to_dict(post)}


@router.get("/", summary="Listar posts")
async def list_posts(
    platform:  Optional[str] = None,
    status:    Optional[str] = None,
    limit:     int = 50,
    offset:    int = 0,
    db: Session = Depends(get_db_session),
):
    """Lista posts con filtros opcionales por plataforma y estado."""
    query = db.query(ScheduledPost)
    if platform:
        query = query.filter_by(platform=platform)
    if status:
        query = query.filter_by(status=status)

    total = query.count()
    posts = query.order_by(ScheduledPost.created_at.desc()).offset(offset).limit(limit).all()

    return {
        "total":  total,
        "limit":  limit,
        "offset": offset,
        "posts":  [_post_to_dict(p) for p in posts],
    }


@router.get("/{post_id}", summary="Detalle de un post")
async def get_post(post_id: int, db: Session = Depends(get_db_session)):
    post = db.query(ScheduledPost).filter_by(id=post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail=f"Post id={post_id} no encontrado.")
    return _post_to_dict(post)


@router.patch("/{post_id}", summary="Editar post")
async def update_post(
    post_id: int,
    body: PostUpdateRequest,
    db: Session = Depends(get_db_session),
):
    """Permite editar un post en estado DRAFT o SCHEDULED."""
    post = db.query(ScheduledPost).filter_by(id=post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail=f"Post id={post_id} no encontrado.")

    if post.status not in (PostStatus.DRAFT, PostStatus.SCHEDULED):
        raise HTTPException(
            status_code=409,
            detail=f"No se puede editar un post en estado '{post.status}'."
        )

    if body.content is not None:
        post.content = body.content
    if body.hashtags is not None:
        post.hashtags = json.dumps(body.hashtags)
    if body.link_url is not None:
        post.link_url = body.link_url

    if body.scheduled_at is not None:
        if body.scheduled_at.tzinfo is None:
            body.scheduled_at = body.scheduled_at.replace(tzinfo=timezone.utc)

        # Cancelar job anterior y reprogramar
        cancel_post_job(post.id)
        post.scheduled_at = body.scheduled_at
        post.status = PostStatus.SCHEDULED
        job_id = schedule_post(post.id, body.scheduled_at)
        post.scheduler_job_id = job_id

    post.updated_at = datetime.now(timezone.utc)
    db.commit()

    return {"status": "updated", "post": _post_to_dict(post)}


@router.delete("/{post_id}", summary="Eliminar post")
async def delete_post(post_id: int, db: Session = Depends(get_db_session)):
    post = db.query(ScheduledPost).filter_by(id=post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail=f"Post id={post_id} no encontrado.")

    if post.status == PostStatus.PUBLISHING:
        raise HTTPException(status_code=409, detail="No se puede eliminar un post en proceso de publicación.")

    cancel_post_job(post.id)
    db.delete(post)
    db.commit()

    logger.info("Post id=%d eliminado.", post_id)
    return {"status": "deleted", "post_id": post_id}


@router.post("/{post_id}/publish-now", summary="Publicar inmediatamente")
async def publish_now(post_id: int, db: Session = Depends(get_db_session)):
    """
    Publica un post de forma inmediata, sin esperar la fecha programada.
    Útil para publicación manual desde el dashboard.
    """
    from datetime import timedelta
    post = db.query(ScheduledPost).filter_by(id=post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail=f"Post id={post_id} no encontrado.")

    if post.status == PostStatus.PUBLISHED:
        raise HTTPException(status_code=409, detail="El post ya está publicado.")

    if post.status == PostStatus.PUBLISHING:
        raise HTTPException(status_code=409, detail="El post ya se está publicando.")

    # Programar en 5 segundos para que el scheduler lo recoja inmediatamente
    run_at = datetime.now(timezone.utc) + timedelta(seconds=5)
    cancel_post_job(post.id)  # Cancelar cualquier job previo
    job_id = schedule_post(post.id, run_at)

    post.scheduled_at     = run_at
    post.status           = PostStatus.SCHEDULED
    post.scheduler_job_id = job_id
    db.commit()

    return {
        "status":  "queued",
        "post_id": post_id,
        "runs_in": "~5 segundos",
        "job_id":  job_id,
    }


@router.get("/scheduler/pending", summary="Jobs pendientes del scheduler")
async def scheduler_pending():
    """Lista los jobs del scheduler que están pendientes de ejecutarse."""
    return {"pending_jobs": list_pending_jobs()}
