"""
main.py — Punto de entrada de NeonStream Social Manager

Arranca la app FastAPI, registra los routers y conecta el scheduler APScheduler.
"""
from __future__ import annotations

import logging

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from rich.logging import RichHandler

from config import get_settings
from models.database import init_db

# ── Logging con Rich (salida estética en terminal) ────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True, markup=True)],
)
logger = logging.getLogger("neonstream")

settings = get_settings()


# ── Lifespan: arranque y apagado controlado ───────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Código que se ejecuta al arrancar y al apagar la aplicación.
    Equivalente al antiguo on_event("startup") / on_event("shutdown").
    """
    # ── Startup ──
    logger.info("[bold magenta]NeonStream arrancando…[/bold magenta]")
    init_db()
    logger.info("Base de datos lista.")

    # Iniciar APScheduler
    from services.scheduler import get_scheduler
    scheduler = get_scheduler()
    scheduler.start()
    logger.info("APScheduler iniciado.")

    yield  # La app corre aquí

    # ── Shutdown ──
    scheduler.shutdown(wait=False)
    logger.info("[bold red]NeonStream apagado.[/bold red]")


# ── Instancia FastAPI ─────────────────────────────────────────────────────────
app = FastAPI(
    title="NeonStream Social Manager",
    description="Gestor unificado de redes sociales con IA — Retrowave Edition",
    version="1.0.0-poc",
    debug=settings.app_debug,
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="app/templates")


# ── Importar y registrar routers ──────────────────────────────────────────────
from app.routes.auth import router as auth_router
from app.routes.posts import router as posts_router
from app.routes.dashboard import router as dashboard_router

app.include_router(auth_router,      prefix="/auth",      tags=["OAuth2"])
app.include_router(posts_router,     prefix="/posts",     tags=["Posts"])
app.include_router(dashboard_router, prefix="/dashboard", tags=["Dashboard"])


@app.get("/", tags=["Health"])
async def root():
    return {
        "app":     "NeonStream Social Manager",
        "version": "1.0.0-poc",
        "status":  "online",
        "docs":    "/docs",
    }


@app.get("/health", tags=["Health"])
async def health():
    return {"status": "ok", "env": settings.app_env}


# ── Arranque directo ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.app_debug,
        log_config=None,  # Dejamos que Rich maneje el logging
    )
