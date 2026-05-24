"""
services/env_manager.py — Lector/escritor del archivo .env

Permite leer y actualizar credenciales de plataformas desde la UI
sin que el usuario tenga que editar el archivo a mano.

Seguridad:
  • Solo escribe claves conocidas (whitelist).
  • Recarga la configuración de Pydantic tras guardar.
  • Nunca expone FERNET_MASTER_KEY ni APP_SECRET_KEY en la UI.
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Claves que la UI puede mostrar y editar (NO incluir claves criptográficas)
EDITABLE_KEYS: dict[str, dict] = {
    # ── Gemini ────────────────────────────────────────────────────────────────
    "GEMINI_API_KEY":            {"label": "API Key",        "platform": "gemini",   "secret": True},
    "GEMINI_MODEL":              {"label": "Modelo",          "platform": "gemini",   "secret": False},
    # ── LinkedIn ──────────────────────────────────────────────────────────────
    "LINKEDIN_CLIENT_ID":        {"label": "Client ID",       "platform": "linkedin", "secret": False},
    "LINKEDIN_CLIENT_SECRET":    {"label": "Client Secret",   "platform": "linkedin", "secret": True},
    "LINKEDIN_REDIRECT_URI":     {"label": "Redirect URI",    "platform": "linkedin", "secret": False},
    # ── X / Twitter ───────────────────────────────────────────────────────────
    "X_CLIENT_ID":               {"label": "Client ID",       "platform": "x_twitter","secret": False},
    "X_CLIENT_SECRET":           {"label": "Client Secret",   "platform": "x_twitter","secret": True},
    "X_REDIRECT_URI":            {"label": "Redirect URI",    "platform": "x_twitter","secret": False},
    # ── Meta / Instagram ──────────────────────────────────────────────────────
    "META_APP_ID":               {"label": "App ID",          "platform": "instagram","secret": False},
    "META_APP_SECRET":           {"label": "App Secret",      "platform": "instagram","secret": True},
    "META_REDIRECT_URI":         {"label": "Redirect URI",    "platform": "instagram","secret": False},
    # ── TikTok ────────────────────────────────────────────────────────────────
    "TIKTOK_CLIENT_KEY":         {"label": "Client Key",      "platform": "tiktok",  "secret": False},
    "TIKTOK_CLIENT_SECRET":      {"label": "Client Secret",   "platform": "tiktok",  "secret": True},
    "TIKTOK_REDIRECT_URI":       {"label": "Redirect URI",    "platform": "tiktok",  "secret": False},
    # ── Telegram ──────────────────────────────────────────────────────────────
    "TELEGRAM_BOT_TOKEN":        {"label": "Bot Token",       "platform": "telegram", "secret": True},
    "TELEGRAM_DEFAULT_CHAT_ID":  {"label": "Chat/Channel ID", "platform": "telegram", "secret": False},
}

# Claves protegidas — nunca mostrar ni editar desde la UI
_PROTECTED = {"FERNET_MASTER_KEY", "APP_SECRET_KEY"}


class EnvManager:
    """Lee y escribe el archivo .env de forma segura."""

    def __init__(self, env_path: Optional[Path] = None) -> None:
        self._path = env_path or self._find_env()

    @staticmethod
    def _find_env() -> Path:
        """Busca el .env en el directorio de trabajo actual."""
        candidates = [
            Path.cwd() / ".env",
            Path(__file__).resolve().parent.parent / ".env",
        ]
        for p in candidates:
            if p.exists():
                return p
        # Si no existe, devolver la ruta preferida para crearlo
        return Path.cwd() / ".env"

    # ── Lectura ───────────────────────────────────────────────────────────────

    def read_all(self) -> dict[str, str]:
        """Lee todas las variables del .env como dict."""
        result: dict[str, str] = {}
        if not self._path.exists():
            return result
        for line in self._path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                result[key.strip()] = value.strip().strip('"').strip("'")
        return result

    def get(self, key: str, default: str = "") -> str:
        return self.read_all().get(key, default)

    def get_platform_values(self, platform: str) -> dict[str, str]:
        """Devuelve los valores actuales de las claves de una plataforma."""
        all_vars = self.read_all()
        return {
            key: all_vars.get(key, "")
            for key, meta in EDITABLE_KEYS.items()
            if meta["platform"] == platform
        }

    # ── Escritura ─────────────────────────────────────────────────────────────

    def set(self, key: str, value: str) -> bool:
        """
        Actualiza o añade una clave en el .env.
        Devuelve True si la operación fue exitosa.
        """
        if key in _PROTECTED:
            logger.warning("Intento de escribir clave protegida '%s' — rechazado.", key)
            return False
        if key not in EDITABLE_KEYS:
            logger.warning("Clave '%s' no está en la whitelist — rechazado.", key)
            return False

        content = self._path.read_text(encoding="utf-8") if self._path.exists() else ""
        pattern = re.compile(rf"^({re.escape(key)}\s*=).*$", re.MULTILINE)

        if pattern.search(content):
            content = pattern.sub(rf"\g<1>{value}", content)
        else:
            content += f"\n{key}={value}\n"

        self._path.write_text(content, encoding="utf-8")
        os.environ[key] = value
        logger.info("Clave '%s' actualizada en .env", key)
        return True

    def set_many(self, values: dict[str, str]) -> dict[str, bool]:
        """Actualiza múltiples claves a la vez. Devuelve dict key→éxito."""
        return {k: self.set(k, v) for k, v in values.items()}

    def reload_config(self) -> None:
        """Recarga el singleton de Settings de Pydantic tras guardar."""
        try:
            from config import get_settings
            get_settings.cache_clear()
            from dotenv import load_dotenv
            load_dotenv(self._path, override=True)
            get_settings()   # re-instanciar
            logger.info("Configuración recargada desde .env")
        except Exception as exc:
            logger.error("Error recargando configuración: %s", exc)

    def has_credentials(self, platform: str) -> bool:
        """Comprueba si una plataforma tiene las credenciales mínimas."""
        required = {
            "linkedin":  ("LINKEDIN_CLIENT_ID", "LINKEDIN_CLIENT_SECRET"),
            "x_twitter": ("X_CLIENT_ID", "X_CLIENT_SECRET"),
            "instagram": ("META_APP_ID", "META_APP_SECRET"),
            "tiktok":    ("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET"),
            "telegram":  ("TELEGRAM_BOT_TOKEN",),
            "gemini":    ("GEMINI_API_KEY",),
        }
        vals = self.read_all()
        return all(vals.get(k, "").strip() not in ("", "TU_CLIENT_ID", "TU_CLIENT_SECRET",
                                                     "TU_APP_ID", "TU_APP_SECRET",
                                                     "TU_CLIENT_KEY", "TU_BOT_TOKEN")
                   for k in required.get(platform, ()))


_manager: Optional[EnvManager] = None

def get_env_manager() -> EnvManager:
    global _manager
    if _manager is None:
        _manager = EnvManager()
    return _manager
