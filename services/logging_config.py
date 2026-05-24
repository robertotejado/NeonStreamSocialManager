"""
services/logging_config.py — Configuración centralizada de logging

Silencia los loggers externos verbosos (kaleido, chromium, SQLAlchemy…)
y configura NeonStream con Rich si está disponible.

Llamar a configure_logging() UNA vez al arrancar, antes de cualquier import.
"""
from __future__ import annotations
import logging

# Loggers externos que no queremos ver salvo errores graves
_SILENT = [
    "sqlalchemy.engine", "sqlalchemy.pool", "sqlalchemy.dialects",
    "sqlalchemy.orm",
    "kaleido", "chromium", "browser_async", "_tmpfile",
    "apscheduler.scheduler", "apscheduler.executors", "apscheduler.jobstores",
    "urllib3", "httpx", "httpcore",
    "asyncio", "concurrent.futures",
    "uvicorn", "uvicorn.error", "uvicorn.access",
    "fastapi",
    "multipart",
    "PIL",
]


def configure_logging(level: int = logging.INFO) -> None:
    """
    Configura el logging de NeonStream.
    - NeonStream: nivel INFO con Rich (si disponible) o basicConfig.
    - Externos: WARNING o ERROR.
    """
    # Intentar Rich
    try:
        from rich.logging import RichHandler
        logging.getLogger().handlers.clear()
        logging.basicConfig(
            level=level,
            format="%(message)s",
            datefmt="[%X]",
            handlers=[RichHandler(rich_tracebacks=True, show_path=False)],
        )
    except ImportError:
        logging.basicConfig(
            level=level,
            format="[%(levelname)s] %(name)s: %(message)s",
        )

    # Silenciar externos
    for name in _SILENT:
        logging.getLogger(name).setLevel(logging.ERROR)

    # NeonStream siempre visible
    logging.getLogger("neonstream").setLevel(level)
