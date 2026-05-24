"""
services/scheduler.py — Gestión de tareas programadas con APScheduler

Responsabilidades:
  • Programar la publicación de un ScheduledPost a la fecha/hora elegida.
  • Ejecutar el job: descifrar token → llamar provider → actualizar estado en DB.
  • Reintentar en caso de fallo (máx. 3 intentos con backoff).
  • Cancelar jobs cuando un post se borra o reprograma.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

from config import get_settings

logger = logging.getLogger(__name__)

_scheduler_instance = None  # BackgroundScheduler o None


def get_scheduler():
    """
    Singleton del scheduler.
    En modo escritorio (CustomTkinter) usamos BackgroundScheduler porque
    AsyncIOScheduler necesita un event loop de asyncio corriendo, que no
    existe en el hilo principal de tkinter.
    BackgroundScheduler corre en su propio hilo y es compatible con CTk.
    """
    global _scheduler_instance
    if _scheduler_instance is None:
        settings = get_settings()
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.executors.pool import ThreadPoolExecutor as TPE
            _scheduler_instance = BackgroundScheduler(
                jobstores={
                    "default": SQLAlchemyJobStore(url=settings.database_url)
                },
                executors={"default": TPE(max_workers=4)},
                job_defaults={
                    "coalesce":          True,
                    "max_instances":     1,
                    "misfire_grace_time": 300,
                },
            )
            logger.info("APScheduler (BackgroundScheduler) inicializado.")
        except Exception as exc:
            logger.error("Error creando scheduler: %s — usando MemoryJobStore", exc)
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.jobstores.memory import MemoryJobStore
            _scheduler_instance = BackgroundScheduler(
                jobstores={"default": MemoryJobStore()},
            )
    return _scheduler_instance


# ── Función que ejecuta el job (llamada por APScheduler) ─────────────────────

def _execute_publish_job(scheduled_post_id: int) -> None:
    """Wrapper síncrono para BackgroundScheduler — ejecuta la corutina en su propio loop."""
    import asyncio
    asyncio.run(_execute_publish_job_async(scheduled_post_id))


async def _execute_publish_job_async(scheduled_post_id: int) -> None:
    """
    Lógica de publicación que corre en el momento programado.

    Diseño intencional:
      • Importaciones locales para evitar circular imports al importar el módulo.
      • Usa su propia sesión DB (no depende del ciclo de vida FastAPI).
      • Actualiza el estado del post (PUBLISHING → PUBLISHED | FAILED).
    """
    from models.database import (
        PostStatus, ScheduledPost, SocialPlatform,
        AuditAction, AuditLog, get_session_factory
    )
    from providers.base import PostContent
    import json

    SessionLocal = get_session_factory()
    db = SessionLocal()

    try:
        post = db.query(ScheduledPost).filter_by(id=scheduled_post_id).first()

        if not post:
            logger.error("Job: ScheduledPost id=%d no encontrado en DB.", scheduled_post_id)
            return

        if post.status not in (PostStatus.SCHEDULED,):
            logger.warning(
                "Job: post id=%d en estado inesperado '%s'. Saltando.", post.id, post.status
            )
            return

        # Marcar como en proceso (lock optimista)
        post.status = PostStatus.PUBLISHING
        db.commit()

        # Obtener credencial y descifrar token (EncryptedString lo hace automáticamente)
        credential = post.credential
        if not credential or not credential.is_active:
            raise RuntimeError(f"Credencial inactiva o no encontrada para post id={post.id}.")

        if credential.is_token_expired() and credential.refresh_token:
            logger.info("Token expirado para post id=%d. Intentando renovar.", post.id)
            await _try_refresh_token(credential, db)

        access_token = credential.access_token  # Descifrado por TypeDecorator
        if not access_token:
            raise RuntimeError("Access token nulo tras descifrado.")

        # Construir PostContent
        hashtags = []
        if post.hashtags:
            try:
                hashtags = json.loads(post.hashtags)
            except json.JSONDecodeError:
                hashtags = [h.strip() for h in post.hashtags.split(",") if h.strip()]

        media_paths = [m.file_path for m in post.media_files]

        content = PostContent(
            text=post.content,
            hashtags=hashtags,
            link_url=post.link_url,
            media_paths=media_paths,
            scheduled_post_id=post.id,
        )

        # Obtener provider dinámicamente según la plataforma
        provider = _get_provider_for_platform(post.platform)

        # Ejecutar el pipeline de publicación
        result = await provider.execute_publish_pipeline(access_token, content)

        if result.success:
            post.status             = PostStatus.PUBLISHED
            post.platform_post_id   = result.platform_post_id
            post.published_at       = datetime.now(timezone.utc)
            post.error_message      = None
            logger.info("Post id=%d publicado en %s. platform_id=%s", post.id, post.platform, result.platform_post_id)

            db.add(AuditLog(
                action=AuditAction.POST_PUBLISHED,
                platform=post.platform,
                entity_id=post.id,
            ))
        else:
            post.retry_count  += 1
            post.error_message = result.error_message

            if post.retry_count >= 3:
                post.status = PostStatus.FAILED
                logger.error("Post id=%d fallido definitivamente tras 3 intentos: %s", post.id, result.error_message)
                db.add(AuditLog(action=AuditAction.POST_FAILED, platform=post.platform, entity_id=post.id))
                _notify_ui(f"Post #{post.id} falló en {post.platform.upper()} ✗", "error")
            else:
                # Reprogramar con backoff exponencial: 5min, 15min, 45min
                post.status = PostStatus.SCHEDULED
                delay_minutes = 5 * (3 ** post.retry_count)
                reschedule_at = datetime.now(timezone.utc) + timedelta(minutes=delay_minutes)
                _schedule_post_job(post.id, reschedule_at)
                logger.warning(
                    "Post id=%d reintento %d/%d en %d min.", post.id, post.retry_count, 3, delay_minutes
                )

        db.commit()

    except Exception as exc:
        logger.exception("Excepción no capturada en job de post id=%d: %s", scheduled_post_id, exc)
        # Intentar marcar como fallido sin propagar para no crashear el scheduler
        try:
            post = db.query(ScheduledPost).filter_by(id=scheduled_post_id).first()
            if post:
                post.status        = PostStatus.FAILED
                post.error_message = str(exc)
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


async def _try_refresh_token(credential, db) -> None:
    """Intenta renovar el access_token usando el refresh_token."""
    from providers.linkedin import create_linkedin_provider
    from providers.x_twitter import create_x_provider
    from models.database import SocialPlatform, AuditAction, AuditLog

    if credential.platform == SocialPlatform.LINKEDIN:
        provider = create_linkedin_provider()
    else:
        logger.warning("Refresh de token no implementado para %s", credential.platform)
        return

    new_tokens = await provider.refresh_access_token(credential.refresh_token)
    credential.access_token       = new_tokens.access_token
    credential.refresh_token      = new_tokens.refresh_token or credential.refresh_token
    credential.token_expires_at   = new_tokens.expires_at
    db.add(AuditLog(action=AuditAction.TOKEN_REFRESHED, platform=credential.platform, entity_id=credential.id))
    db.commit()
    logger.info("Token renovado para credencial id=%d.", credential.id)


def _get_provider_for_platform(platform: str):
    """Devuelve el provider correcto para la plataforma dada."""
    from models.database import SocialPlatform
    from providers.linkedin import create_linkedin_provider
    from providers.x_twitter import create_x_provider
    from providers.tiktok import create_tiktok_provider
    from providers.telegram import create_telegram_provider
    from providers.instagram import create_instagram_provider

    mapping = {
        SocialPlatform.LINKEDIN:  create_linkedin_provider,
        SocialPlatform.X_TWITTER: create_x_provider,
        SocialPlatform.TIKTOK:    create_tiktok_provider,
        SocialPlatform.INSTAGRAM: create_instagram_provider,
        # Telegram publica via Bot API directa — manejo especial en el job
    }
    factory = mapping.get(platform)
    if not factory:
        raise NotImplementedError(f"No hay provider implementado para '{platform}'.")
    return factory()


# ── API pública del scheduler ─────────────────────────────────────────────────

def _schedule_post_job(post_id: int, run_at: datetime) -> str:
    """
    Registra (o reemplaza) el job de publicación para un post.

    Returns:
        El job_id de APScheduler (= "post_{post_id}").
    """
    scheduler = get_scheduler()
    job_id = f"post_{post_id}"

    # replace_existing=True para manejar reprogramaciones
    scheduler.add_job(
        _execute_publish_job,
        trigger="date",
        run_date=run_at,
        args=[post_id],
        id=job_id,
        replace_existing=True,
        name=f"Publicar post #{post_id}",
    )
    logger.info("Job programado: post_id=%d a las %s (UTC)", post_id, run_at.isoformat())
    return job_id


def schedule_post(post_id: int, scheduled_at: datetime) -> str:
    """
    Punto de entrada público. Programa la publicación de un post.

    Args:
        post_id:      ID del ScheduledPost en DB.
        scheduled_at: Fecha/hora de publicación (timezone-aware UTC).

    Returns:
        job_id del scheduler.
    """
    if scheduled_at.tzinfo is None:
        scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)
    return _schedule_post_job(post_id, scheduled_at)


def cancel_post_job(post_id: int) -> bool:
    """
    Cancela el job programado para un post.

    Returns:
        True si el job existía y fue cancelado, False si no existía.
    """
    scheduler = get_scheduler()
    job_id = f"post_{post_id}"
    job = scheduler.get_job(job_id)
    if job:
        scheduler.remove_job(job_id)
        logger.info("Job cancelado: post_id=%d", post_id)
        return True
    return False


def list_pending_jobs() -> list[dict]:
    """Lista los jobs pendientes del scheduler (útil para debugging)."""
    scheduler = get_scheduler()
    return [
        {
            "job_id":   job.id,
            "name":     job.name,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
        }
        for job in scheduler.get_jobs()
    ]
