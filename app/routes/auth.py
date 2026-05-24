"""
app/routes/auth.py — Rutas de autenticación OAuth2

Flujo completo para LinkedIn (PoC):
  GET  /auth/linkedin/login     → redirige al portal de LinkedIn
  GET  /auth/linkedin/callback  → recibe code+state, guarda tokens cifrados en DB
  POST /auth/linkedin/revoke    → revoca tokens y desactiva la credencial
  GET  /auth/status             → lista plataformas conectadas
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from models.database import (
    AuditAction, AuditLog, SocialCredential, SocialPlatform, get_db_session
)
from providers.linkedin import create_linkedin_provider

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Helper: registrar en audit_log ────────────────────────────────────────────

def _audit(
    db: Session,
    action: AuditAction,
    platform: str,
    entity_id: Optional[int] = None,
    detail: Optional[dict] = None,
    request: Optional[Request] = None,
) -> None:
    ip = request.client.host if request and request.client else None
    db.add(AuditLog(
        action=action,
        platform=platform,
        entity_id=entity_id,
        detail=json.dumps(detail) if detail else None,
        ip_address=ip,
    ))


# ══════════════════════════════════════════════════════════════════════════════
#  LinkedIn OAuth2
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/linkedin/login", summary="Iniciar autenticación LinkedIn")
async def linkedin_login(request: Request):
    """
    Genera la URL de autorización LinkedIn y redirige al usuario.
    Guarda el state anti-CSRF en la sesión de la petición.

    Para testing sin frontend: acceder directamente en el navegador.
    """
    provider = create_linkedin_provider()
    auth_url, state = provider.get_authorization_url()

    # En producción usar sesiones firmadas (itsdangerous / starlette SessionMiddleware).
    # Para el PoC guardamos el state en la query de retorno (NO hacer en prod).
    # TODO: añadir SessionMiddleware y guardar state en session["oauth_state"]
    logger.info("LinkedIn OAuth iniciado. Redirigiendo al portal de autorización.")

    # Devolvemos la URL para que el frontend redirija (o redirigimos directamente)
    return JSONResponse({
        "authorization_url": auth_url,
        "state": state,
        "note": "Redirige el navegador a authorization_url y guarda state en sesión."
    })


@router.get("/linkedin/callback", summary="Callback OAuth2 LinkedIn")
async def linkedin_callback(
    request:  Request,
    code:     Optional[str]  = Query(None),
    state:    Optional[str]  = Query(None),
    error:    Optional[str]  = Query(None),
    error_description: Optional[str] = Query(None),
    expected_state: Optional[str] = Query(None, alias="expected_state"),
    db: Session = Depends(get_db_session),
):
    """
    Recibe el callback de LinkedIn tras la autorización del usuario.

    Query params (enviados por LinkedIn):
      code  — authorization code para intercambiar por tokens
      state — debe coincidir con el enviado en /login
      error — si el usuario denegó el permiso

    Query param adicional (PoC — en prod viene de la sesión):
      expected_state — el state que generamos en /login
    """
    # ── Error devuelto por LinkedIn ───────────────────────────────────────────
    if error:
        logger.warning("LinkedIn denegó la autorización: %s — %s", error, error_description)
        raise HTTPException(
            status_code=400,
            detail=f"LinkedIn denegó el acceso: {error_description or error}",
        )

    if not code or not state:
        raise HTTPException(status_code=400, detail="Faltan parámetros code o state en el callback.")

    # ── Verificación de state (anti-CSRF) ─────────────────────────────────────
    # En producción: expected_state = request.session.get("oauth_state")
    if not expected_state:
        raise HTTPException(
            status_code=400,
            detail="No se encontró el expected_state. "
                   "En PoC pásalo como query param; en prod usar sesiones."
        )

    # ── Intercambio de código por tokens ─────────────────────────────────────
    provider = create_linkedin_provider()
    try:
        tokens = await provider.handle_callback(code, state, expected_state)
    except ValueError as exc:
        logger.error("CSRF state mismatch: %s", exc)
        raise HTTPException(status_code=403, detail=str(exc))
    except PermissionError as exc:
        logger.error("LinkedIn rechazó el token exchange: %s", exc)
        raise HTTPException(status_code=401, detail=str(exc))

    # ── Obtener perfil del usuario ────────────────────────────────────────────
    try:
        profile = await provider.get_user_profile(tokens.access_token)
    except Exception as exc:
        logger.error("Error obteniendo perfil LinkedIn: %s", exc)
        raise HTTPException(status_code=502, detail=f"No se pudo obtener el perfil: {exc}")

    # ── Guardar o actualizar credencial en DB (tokens cifrados automáticamente) ──
    existing = (
        db.query(SocialCredential)
        .filter_by(platform=SocialPlatform.LINKEDIN, external_user_id=profile.external_user_id)
        .first()
    )

    if existing:
        # Reconexión — actualizar tokens
        existing.access_token         = tokens.access_token
        existing.refresh_token        = tokens.refresh_token
        existing.token_expires_at     = tokens.expires_at
        existing.scopes               = " ".join(tokens.scopes) if tokens.scopes else None
        existing.username             = profile.username
        existing.display_name         = profile.display_name
        existing.profile_picture_url  = profile.profile_picture_url
        existing.is_active            = True
        existing.updated_at           = datetime.now(timezone.utc)
        credential = existing
        action = AuditAction.TOKEN_REFRESHED
        logger.info("Credencial LinkedIn actualizada para user=%s", profile.username)
    else:
        # Primera conexión — crear nueva credencial
        credential = SocialCredential(
            platform=SocialPlatform.LINKEDIN,
            external_user_id=profile.external_user_id,
            username=profile.username,
            display_name=profile.display_name,
            profile_picture_url=profile.profile_picture_url,
            access_token=tokens.access_token,   # ← EncryptedString cifra automáticamente
            refresh_token=tokens.refresh_token, # ← idem
            token_expires_at=tokens.expires_at,
            scopes=" ".join(tokens.scopes) if tokens.scopes else None,
            is_active=True,
        )
        db.add(credential)
        db.flush()  # Para obtener el ID antes del commit
        action = AuditAction.AUTH_COMPLETED
        logger.info("Nueva credencial LinkedIn creada para user=%s", profile.username)

    # ── Registrar en audit_log ────────────────────────────────────────────────
    _audit(
        db, action,
        platform="linkedin",
        entity_id=credential.id,
        detail={"username": profile.username, "scopes": tokens.scopes},
        request=request,
    )

    return JSONResponse({
        "status":        "connected",
        "platform":      "linkedin",
        "display_name":  profile.display_name,
        "username":      profile.username,
        "credential_id": credential.id,
        "expires_at":    tokens.expires_at.isoformat() if tokens.expires_at else None,
        "message":       f"LinkedIn conectado correctamente para {profile.display_name}."
    })


@router.post("/linkedin/revoke", summary="Revocar tokens LinkedIn")
async def linkedin_revoke(
    credential_id: int,
    request: Request,
    db: Session = Depends(get_db_session),
):
    """
    Revoca el access_token de una credencial LinkedIn y la desactiva en DB.
    """
    credential = db.query(SocialCredential).filter_by(
        id=credential_id, platform=SocialPlatform.LINKEDIN
    ).first()

    if not credential:
        raise HTTPException(status_code=404, detail="Credencial no encontrada.")

    # Revocar en LinkedIn (el campo se descifra automáticamente por EncryptedString)
    provider = create_linkedin_provider()
    if credential.access_token:
        await provider.revoke_token(credential.access_token)

    # Limpiar tokens en DB y desactivar
    credential.access_token   = None
    credential.refresh_token  = None
    credential.is_active      = False
    credential.updated_at     = datetime.now(timezone.utc)

    _audit(db, AuditAction.TOKEN_REVOKED, "linkedin", entity_id=credential.id, request=request)

    return {"status": "revoked", "credential_id": credential_id}


# ══════════════════════════════════════════════════════════════════════════════
#  Estado general de conexiones
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/status", summary="Estado de plataformas conectadas")
async def auth_status(db: Session = Depends(get_db_session)):
    """Lista todas las cuentas conectadas con sus estados."""
    credentials = db.query(SocialCredential).filter_by(is_active=True).all()

    return {
        "connected_accounts": [
            {
                "id":           c.id,
                "platform":     c.platform,
                "display_name": c.display_name,
                "username":     c.username,
                "is_active":    c.is_active,
                "token_expired": c.is_token_expired(),
                "expires_at":   c.token_expires_at.isoformat() if c.token_expires_at else None,
                "connected_at": c.created_at.isoformat(),
            }
            for c in credentials
        ],
        "total": len(credentials),
    }
