"""
tests/conftest.py — Fixtures y configuración global de pytest

Garantiza que todos los tests:
  • Tengan un .env mínimo válido (monkeypatched)
  • Usen SQLite en memoria (nunca el neonstream.db real)
  • Reseteen los singletons entre tests
  • Tengan asyncio configurado correctamente
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

# Asegurar que el root del proyecto esté en sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ── Configuración asyncio ─────────────────────────────────────────────────────

def pytest_configure(config):
    """Registra el marcador asyncio para evitar warnings."""
    config.addinivalue_line(
        "markers", "asyncio: marca un test como corutina asyncio"
    )


# ── Fixture global: entorno mínimo ────────────────────────────────────────────

@pytest.fixture(autouse=True)
def minimal_env(monkeypatch):
    """
    Inyecta las variables de entorno mínimas para que Settings no falle.
    Se aplica a TODOS los tests automáticamente.
    """
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("FERNET_MASTER_KEY",        key)
    monkeypatch.setenv("APP_SECRET_KEY",            "a" * 32)
    monkeypatch.setenv("DATABASE_URL",              "sqlite:///:memory:")
    monkeypatch.setenv("LINKEDIN_CLIENT_ID",        "test_li_client_id")
    monkeypatch.setenv("LINKEDIN_CLIENT_SECRET",    "test_li_client_secret")
    monkeypatch.setenv("LINKEDIN_REDIRECT_URI",     "http://localhost:8000/auth/linkedin/callback")
    monkeypatch.setenv("LINKEDIN_SCOPES",           "openid,profile,email,w_member_social")
    monkeypatch.setenv("GEMINI_API_KEY",            "AIza_TU_API_KEY_AQUI")
    monkeypatch.setenv("X_CLIENT_ID",               "")
    monkeypatch.setenv("X_CLIENT_SECRET",           "")
    monkeypatch.setenv("META_APP_ID",               "")
    monkeypatch.setenv("META_APP_SECRET",           "")
    monkeypatch.setenv("TIKTOK_CLIENT_KEY",         "")
    monkeypatch.setenv("TIKTOK_CLIENT_SECRET",      "")

    # Invalidar singletons cacheados
    from config import get_settings
    get_settings.cache_clear()

    import services.crypto as crypto_mod
    crypto_mod._crypto_instance = None

    yield

    # Limpiar singletons tras cada test
    get_settings.cache_clear()
    crypto_mod._crypto_instance = None


# ── Fixture: sesión de BD en memoria ─────────────────────────────────────────

@pytest.fixture
def db_session():
    """
    Sesión SQLAlchemy en memoria con el schema completo.
    Hace rollback automático al finalizar cada test.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from models.database import Base

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()

    yield session

    session.rollback()
    session.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


# ── Fixture: crypto service ───────────────────────────────────────────────────

@pytest.fixture
def crypto():
    """Instancia fresca de CryptoService para cada test."""
    import services.crypto as crypto_mod
    crypto_mod._crypto_instance = None
    svc = crypto_mod.get_crypto()
    yield svc
    crypto_mod._crypto_instance = None


# ── Fixture: LinkedIn provider ────────────────────────────────────────────────

@pytest.fixture
def linkedin_provider():
    from providers.linkedin import LinkedInProvider
    return LinkedInProvider(
        client_id="test_client_id",
        client_secret="test_secret",
        redirect_uri="http://localhost:8000/auth/linkedin/callback",
        scopes=["openid", "profile", "email", "w_member_social"],
    )
