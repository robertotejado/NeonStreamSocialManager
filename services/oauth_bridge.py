"""
services/oauth_bridge.py — Servidor OAuth en hilo daemon

Problema:
  CustomTkinter corre en el hilo principal. Los callbacks OAuth2 de LinkedIn,
  X, etc. llegan via HTTP redirect al navegador → localhost:8000.
  CTk no puede escuchar HTTP, y FastAPI no puede tocar widgets CTk directamente.

Solución:
  Un servidor uvicorn minimalista corre en un hilo daemon (threading.Thread).
  Cuando llega un callback OAuth, guarda los tokens en DB y emite un evento
  (threading.Event) que el hilo UI puede escuchar con .after() para actualizar
  la interfaz sin bloquear.

Flujo:
  1. UI llama a OAuthBridge.start_oauth_flow("linkedin")
     → genera URL de auth + state
     → abre el navegador del sistema con webbrowser.open()
  2. El usuario autoriza en LinkedIn
  3. LinkedIn redirige a http://localhost:8000/auth/linkedin/callback?code=...
  4. El mini-servidor procesa el callback (guarda tokens cifrados en DB)
  5. OAuthBridge.completion_events["linkedin"].set() → UI lo detecta y refresca

Thread safety:
  DB sessions: cada hilo crea su propia sesión (get_session_factory).
  state store: dict protegido con threading.Lock().
  Notificación UI: solo via Event + CTk.after(). Nunca tocar widgets desde el daemon.
"""
from __future__ import annotations

import logging
import threading
import webbrowser
from typing import Callable, Optional

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  Estado compartido entre hilos (thread-safe)
# ══════════════════════════════════════════════════════════════════════════════

class _SharedState:
    """Almacén thread-safe de states OAuth y eventos de completado."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._states: dict[str, str] = {}          # platform → state
        self._errors: dict[str, str] = {}           # platform → error msg
        self._results: dict[str, dict] = {}         # platform → profile data
        self.completion_events: dict[str, threading.Event] = {}

    def store_state(self, platform: str, state: str) -> None:
        with self._lock:
            self._states[platform] = state
            self.completion_events[platform] = threading.Event()
            self._errors.pop(platform, None)
            self._results.pop(platform, None)

    def get_state(self, platform: str) -> Optional[str]:
        with self._lock:
            return self._states.get(platform)

    def set_result(self, platform: str, result: dict) -> None:
        with self._lock:
            self._results[platform] = result
            self.completion_events[platform].set()

    def set_error(self, platform: str, error: str) -> None:
        with self._lock:
            self._errors[platform] = error
            if platform in self.completion_events:
                self.completion_events[platform].set()

    def get_result(self, platform: str) -> Optional[dict]:
        with self._lock:
            return self._results.get(platform)

    def get_error(self, platform: str) -> Optional[str]:
        with self._lock:
            return self._errors.get(platform)


_shared = _SharedState()


# ══════════════════════════════════════════════════════════════════════════════
#  Mini-servidor FastAPI (solo para callbacks OAuth)
# ══════════════════════════════════════════════════════════════════════════════

def _build_callback_app():
    """
    Construye la app FastAPI minimalista solo con las rutas de callback OAuth.
    Se importa tarde para evitar circular imports.
    """
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse

    callback_app = FastAPI(title="NeonStream OAuth Callback", docs_url=None, redoc_url=None)

    # ── LinkedIn callback ─────────────────────────────────────────────────────

    @callback_app.get("/auth/linkedin/callback")
    async def linkedin_callback(
        code: Optional[str] = None,
        state: Optional[str] = None,
        error: Optional[str] = None,
        error_description: Optional[str] = None,
    ):
        platform = "linkedin"

        if error:
            msg = error_description or error
            _shared.set_error(platform, msg)
            return HTMLResponse(_oauth_result_page(success=False, message=msg, platform="LinkedIn"))

        expected_state = _shared.get_state(platform)
        if not expected_state:
            msg = "No se encontró sesión OAuth activa. Intenta conectar de nuevo desde la app."
            _shared.set_error(platform, msg)
            return HTMLResponse(_oauth_result_page(False, msg, "LinkedIn"))

        try:
            from providers.linkedin import create_linkedin_provider
            from models.database import (
                SocialCredential, SocialPlatform,
                AuditAction, AuditLog, get_session_factory,
            )
            from datetime import datetime, timezone

            provider = create_linkedin_provider()
            tokens = await provider.handle_callback(code, state, expected_state)
            profile = await provider.get_user_profile(tokens.access_token)

            # Guardar en DB (sesión propia del hilo daemon)
            SessionLocal = get_session_factory()
            db = SessionLocal()
            try:
                existing = db.query(SocialCredential).filter_by(
                    platform=SocialPlatform.LINKEDIN,
                    external_user_id=profile.external_user_id,
                ).first()

                if existing:
                    existing.access_token        = tokens.access_token
                    existing.refresh_token       = tokens.refresh_token
                    existing.token_expires_at    = tokens.expires_at
                    existing.scopes              = " ".join(tokens.scopes or [])
                    existing.username            = profile.username
                    existing.display_name        = profile.display_name
                    existing.profile_picture_url = profile.profile_picture_url
                    existing.is_active           = True
                    existing.updated_at          = datetime.now(timezone.utc)
                    credential_id = existing.id
                else:
                    cred = SocialCredential(
                        platform=SocialPlatform.LINKEDIN,
                        external_user_id=profile.external_user_id,
                        username=profile.username,
                        display_name=profile.display_name,
                        profile_picture_url=profile.profile_picture_url,
                        access_token=tokens.access_token,
                        refresh_token=tokens.refresh_token,
                        token_expires_at=tokens.expires_at,
                        scopes=" ".join(tokens.scopes or []),
                        is_active=True,
                    )
                    db.add(cred)
                    db.flush()
                    credential_id = cred.id

                db.add(AuditLog(
                    action=AuditAction.AUTH_COMPLETED,
                    platform="linkedin",
                    entity_id=credential_id,
                ))
                db.commit()
            finally:
                db.close()

            result = {
                "credential_id": credential_id,
                "display_name":  profile.display_name,
                "username":      profile.username,
            }
            _shared.set_result(platform, result)

            msg = f"¡Conectado como {profile.display_name}! Puedes cerrar esta ventana."
            return HTMLResponse(_oauth_result_page(True, msg, "LinkedIn"))

        except Exception as exc:
            logger.exception("Error en callback LinkedIn: %s", exc)
            _shared.set_error(platform, str(exc))
            return HTMLResponse(_oauth_result_page(False, str(exc), "LinkedIn"))

    # ── X/Twitter callback (Fase 2) ──────────────────────────────────────────

    @callback_app.get("/auth/x/callback")
    async def x_callback(
        code:  Optional[str] = None,
        state: Optional[str] = None,
        error: Optional[str] = None,
        error_description: Optional[str] = None,
    ):
        platform = "x_twitter"

        if error:
            msg = error_description or error
            _shared.set_error(platform, msg)
            return HTMLResponse(_oauth_result_page(False, msg, "X / Twitter"))

        expected_state = _shared.get_state(platform)
        if not expected_state:
            msg = "No se encontró sesión OAuth activa para X. Intenta de nuevo."
            _shared.set_error(platform, msg)
            return HTMLResponse(_oauth_result_page(False, msg, "X / Twitter"))

        try:
            from providers.x_twitter import create_x_provider
            from models.database import (
                SocialCredential, SocialPlatform,
                AuditAction, AuditLog, get_session_factory,
            )
            from datetime import datetime, timezone

            provider = create_x_provider()
            tokens   = await provider.handle_callback(code, state, expected_state)
            profile  = await provider.get_user_profile(tokens.access_token)

            SessionLocal = get_session_factory()
            db = SessionLocal()
            try:
                existing = db.query(SocialCredential).filter_by(
                    platform=SocialPlatform.X_TWITTER,
                    external_user_id=profile.external_user_id,
                ).first()

                if existing:
                    existing.access_token        = tokens.access_token
                    existing.refresh_token       = tokens.refresh_token
                    existing.token_expires_at    = tokens.expires_at
                    existing.scopes              = " ".join(tokens.scopes or [])
                    existing.username            = profile.username
                    existing.display_name        = profile.display_name
                    existing.is_active           = True
                    existing.updated_at          = datetime.now(timezone.utc)
                    credential_id = existing.id
                else:
                    cred = SocialCredential(
                        platform=SocialPlatform.X_TWITTER,
                        external_user_id=profile.external_user_id,
                        username=profile.username,
                        display_name=profile.display_name,
                        access_token=tokens.access_token,
                        refresh_token=tokens.refresh_token,
                        token_expires_at=tokens.expires_at,
                        scopes=" ".join(tokens.scopes or []),
                        is_active=True,
                    )
                    db.add(cred)
                    db.flush()
                    credential_id = cred.id

                db.add(AuditLog(
                    action=AuditAction.AUTH_COMPLETED,
                    platform="x_twitter",
                    entity_id=credential_id,
                ))
                db.commit()
            finally:
                db.close()

            result = {
                "credential_id": credential_id,
                "display_name":  profile.display_name,
                "username":      profile.username,
            }
            _shared.set_result(platform, result)
            msg = f"¡Conectado como @{profile.username}! Puedes cerrar esta ventana."
            return HTMLResponse(_oauth_result_page(True, msg, "X / Twitter"))

        except Exception as exc:
            logger.exception("Error en callback X: %s", exc)
            _shared.set_error(platform, str(exc))
            return HTMLResponse(_oauth_result_page(False, str(exc), "X / Twitter"))

    # ── TikTok callback (Fase 3) ─────────────────────────────────────────────

    @callback_app.get("/auth/tiktok/callback")
    async def tiktok_callback(
        code:  Optional[str] = None,
        state: Optional[str] = None,
        error: Optional[str] = None,
        error_description: Optional[str] = None,
    ):
        platform = "tiktok"
        if error:
            msg = error_description or error
            _shared.set_error(platform, msg)
            return HTMLResponse(_oauth_result_page(False, msg, "TikTok"))

        expected_state = _shared.get_state(platform)
        if not expected_state:
            msg = "No hay sesión OAuth activa para TikTok."
            _shared.set_error(platform, msg)
            return HTMLResponse(_oauth_result_page(False, msg, "TikTok"))

        try:
            from providers.tiktok import create_tiktok_provider
            from models.database import (
                SocialCredential, SocialPlatform,
                AuditAction, AuditLog, get_session_factory,
            )
            from datetime import datetime, timezone

            provider = create_tiktok_provider()
            tokens   = await provider.handle_callback(code, state, expected_state)
            profile  = await provider.get_user_profile(tokens.access_token)

            SessionLocal = get_session_factory()
            db = SessionLocal()
            try:
                existing = db.query(SocialCredential).filter_by(
                    platform=SocialPlatform.TIKTOK,
                    external_user_id=profile.external_user_id,
                ).first()
                if existing:
                    existing.access_token     = tokens.access_token
                    existing.refresh_token    = tokens.refresh_token
                    existing.token_expires_at = tokens.expires_at
                    existing.display_name     = profile.display_name
                    existing.username         = profile.username
                    existing.is_active        = True
                    existing.updated_at       = datetime.now(timezone.utc)
                    credential_id = existing.id
                else:
                    cred = SocialCredential(
                        platform=SocialPlatform.TIKTOK,
                        external_user_id=profile.external_user_id,
                        username=profile.username,
                        display_name=profile.display_name,
                        access_token=tokens.access_token,
                        refresh_token=tokens.refresh_token,
                        token_expires_at=tokens.expires_at,
                        is_active=True,
                    )
                    db.add(cred)
                    db.flush()
                    credential_id = cred.id
                db.add(AuditLog(action=AuditAction.AUTH_COMPLETED,
                                platform="tiktok", entity_id=credential_id))
                db.commit()
            finally:
                db.close()

            _shared.set_result(platform, {"credential_id": credential_id,
                                           "display_name": profile.display_name})
            msg = f"¡TikTok conectado como {profile.display_name}!"
            return HTMLResponse(_oauth_result_page(True, msg, "TikTok"))

        except Exception as exc:
            logger.exception("Error callback TikTok: %s", exc)
            _shared.set_error(platform, str(exc))
            return HTMLResponse(_oauth_result_page(False, str(exc), "TikTok"))


    # ── Instagram/Meta callback (Fase 4) ─────────────────────────────────────

    @callback_app.get("/auth/meta/callback")
    async def meta_callback(
        code:  Optional[str] = None,
        state: Optional[str] = None,
        error: Optional[str] = None,
        error_description: Optional[str] = None,
    ):
        platform = "instagram"
        if error:
            msg = error_description or error
            _shared.set_error(platform, msg)
            return HTMLResponse(_oauth_result_page(False, msg, "Instagram"))

        expected_state = _shared.get_state(platform)
        if not expected_state:
            msg = "No hay sesión OAuth activa para Instagram."
            _shared.set_error(platform, msg)
            return HTMLResponse(_oauth_result_page(False, msg, "Instagram"))

        try:
            from providers.instagram import create_instagram_provider
            from models.database import (
                SocialCredential, SocialPlatform,
                AuditAction, AuditLog, get_session_factory,
            )
            from datetime import datetime, timezone

            provider = create_instagram_provider()
            tokens   = await provider.handle_callback(code, state, expected_state)
            profile  = await provider.get_user_profile(tokens.access_token)

            SessionLocal = get_session_factory()
            db = SessionLocal()
            try:
                existing = db.query(SocialCredential).filter_by(
                    platform=SocialPlatform.INSTAGRAM,
                    external_user_id=profile.external_user_id,
                ).first()
                if existing:
                    existing.access_token     = tokens.access_token
                    existing.token_expires_at = tokens.expires_at
                    existing.display_name     = profile.display_name
                    existing.username         = profile.username
                    existing.is_active        = True
                    existing.updated_at       = datetime.now(timezone.utc)
                    credential_id = existing.id
                else:
                    cred = SocialCredential(
                        platform=SocialPlatform.INSTAGRAM,
                        external_user_id=profile.external_user_id,
                        username=profile.username,
                        display_name=profile.display_name,
                        access_token=tokens.access_token,
                        token_expires_at=tokens.expires_at,
                        is_active=True,
                    )
                    db.add(cred)
                    db.flush()
                    credential_id = cred.id
                db.add(AuditLog(action=AuditAction.AUTH_COMPLETED,
                                platform="instagram", entity_id=credential_id))
                db.commit()
            finally:
                db.close()

            _shared.set_result(platform, {"credential_id": credential_id,
                                           "display_name": profile.display_name})
            msg = f"Instagram conectado como {profile.display_name}!"
            return HTMLResponse(_oauth_result_page(True, msg, "Instagram"))

        except Exception as exc:
            logger.exception("Error callback Instagram: %s", exc)
            _shared.set_error(platform, str(exc))
            return HTMLResponse(_oauth_result_page(False, str(exc), "Instagram"))

    return callback_app


def _oauth_result_page(success: bool, message: str, platform: str) -> str:
    """Genera la página HTML que ve el usuario en el navegador tras el callback."""
    color = "#00f5e9" if success else "#ff2d78"
    icon  = "✓" if success else "✗"
    bg    = "#0d0d1a"
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>NeonStream — {platform}</title>
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
      background: {bg};
      color: #e8e8ff;
      font-family: 'Segoe UI', sans-serif;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
    }}
    .card {{
      text-align: center;
      padding: 48px 64px;
      border: 1px solid {color};
      border-radius: 16px;
      max-width: 480px;
      box-shadow: 0 0 40px {color}33;
    }}
    .icon {{ font-size: 64px; color: {color}; margin-bottom: 16px; }}
    .platform {{ font-size: 12px; letter-spacing: 4px; color: #7a7ab8;
                 text-transform: uppercase; margin-bottom: 8px; }}
    h1 {{ font-size: 20px; margin-bottom: 16px; }}
    p {{ color: #7a7ab8; font-size: 14px; line-height: 1.6; }}
    .close-hint {{ margin-top: 24px; font-size: 12px; color: #3a3a6a; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">{icon}</div>
    <div class="platform">{platform}</div>
    <h1>{"Conexión exitosa" if success else "Error de conexión"}</h1>
    <p>{message}</p>
    <p class="close-hint">Puedes cerrar esta pestaña y volver a NeonStream.</p>
  </div>
  <script>if ({str(success).lower()}) {{ setTimeout(() => window.close(), 3000); }}</script>
</body>
</html>"""


# ══════════════════════════════════════════════════════════════════════════════
#  OAuthBridge — interfaz pública para la UI
# ══════════════════════════════════════════════════════════════════════════════

class OAuthBridge:
    """
    Gestiona el servidor OAuth daemon y los flujos de autenticación.

    Uso desde la UI:
        bridge = OAuthBridge()
        bridge.start_server()   # arranca el daemon una vez al inicio
        bridge.start_oauth_flow("linkedin", on_complete=self._on_linkedin_connected)
    """

    def __init__(self, port: int = 8000) -> None:
        self._port = port
        self._server_thread: Optional[threading.Thread] = None
        self._server_started = threading.Event()

    def start_server(self) -> None:
        """Arranca el mini-servidor uvicorn en un hilo daemon."""
        if self._server_thread and self._server_thread.is_alive():
            logger.debug("OAuthBridge: servidor ya corriendo.")
            return

        self._server_thread = threading.Thread(
            target=self._run_server,
            name="oauth-bridge",
            daemon=True,   # Muere automáticamente cuando cierra la app CTk
        )
        self._server_thread.start()
        # Esperar hasta 3 segundos a que el servidor esté listo
        self._server_started.wait(timeout=3.0)
        logger.info("OAuthBridge: servidor en http://localhost:%d", self._port)

    def _run_server(self) -> None:
        """Función que corre en el hilo daemon."""
        import uvicorn

        app = _build_callback_app()

        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=self._port,
            log_level="error",
            access_log=False,
        )
        server = uvicorn.Server(config)

        # Señalar que el servidor está listo antes de correr
        # (uvicorn llama a startup hooks antes del bucle principal)
        import asyncio

        async def _serve():
            await server.serve()

        async def _start():
            # Pequeño hack: señalamos ready después de que uvicorn inicie
            loop = asyncio.get_event_loop()
            loop.call_later(0.5, self._server_started.set)
            await _serve()

        asyncio.run(_start())

    def start_oauth_flow(
        self,
        platform: str,
        on_complete: Optional[Callable[[dict], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ) -> None:
        """
        Inicia el flujo OAuth para una plataforma:
          1. Genera la URL de autorización.
          2. Abre el navegador del sistema.
          3. Espera el evento de completado en un hilo background.
          4. Llama a on_complete(result) o on_error(msg) cuando termina.

        Args:
            platform:    "linkedin" | "x_twitter" | "instagram" …
            on_complete: Callback con el resultado (se ejecuta en hilo background,
                         usar CTk.after() para actualizar la UI).
            on_error:    Callback de error.
        """
        if platform == "linkedin":
            from providers.linkedin import create_linkedin_provider
            provider = create_linkedin_provider()
            auth_url, state = provider.get_authorization_url()
        elif platform == "x_twitter":
            from providers.x_twitter import create_x_provider
            provider = create_x_provider()
            auth_url, state = provider.get_authorization_url()
        elif platform == "tiktok":
            from providers.tiktok import create_tiktok_provider
            provider = create_tiktok_provider()
            auth_url, state = provider.get_authorization_url()
        elif platform == "instagram":
            from providers.instagram import create_instagram_provider
            provider = create_instagram_provider()
            auth_url, state = provider.get_authorization_url()
        elif platform == "telegram":
            # Telegram no usa OAuth — verificar token directamente
            if on_error:
                on_error("Telegram no usa OAuth2. Configura el Bot Token en Credenciales.")
            return
        else:
            if on_error:
                on_error(f"Provider '{platform}' no implementado aún.")
            return

        _shared.store_state(platform, state)
        webbrowser.open(auth_url)
        logger.info("Navegador abierto para OAuth %s.", platform)

        # Esperar en hilo background para no bloquear la UI
        wait_thread = threading.Thread(
            target=self._wait_for_completion,
            args=(platform, on_complete, on_error),
            daemon=True,
        )
        wait_thread.start()

    def _wait_for_completion(
        self,
        platform: str,
        on_complete: Optional[Callable],
        on_error: Optional[Callable],
        timeout: float = 300.0,   # 5 minutos para que el usuario autorice
    ) -> None:
        """Espera el evento de completado y llama al callback apropiado."""
        event = _shared.completion_events.get(platform)
        if not event:
            return

        finished = event.wait(timeout=timeout)

        if not finished:
            msg = f"Timeout: el usuario no completó la autorización de {platform} en {int(timeout)}s."
            logger.warning(msg)
            if on_error:
                on_error(msg)
            return

        error = _shared.get_error(platform)
        result = _shared.get_result(platform)

        if error:
            logger.error("OAuth %s error: %s", platform, error)
            if on_error:
                on_error(error)
        elif result:
            logger.info("OAuth %s completado: %s", platform, result)
            if on_complete:
                on_complete(result)


# ── Singleton global ──────────────────────────────────────────────────────────

_bridge_instance: Optional[OAuthBridge] = None


def get_oauth_bridge() -> OAuthBridge:
    global _bridge_instance
    if _bridge_instance is None:
        _bridge_instance = OAuthBridge()
    return _bridge_instance
