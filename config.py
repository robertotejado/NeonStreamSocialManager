"""
config.py — Configuración central de NeonStream
Lee variables desde .env y las valida con Pydantic Settings.
"""
from functools import lru_cache
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────────────────────────────
    app_env: str = Field(default="development")
    app_secret_key: str = Field(..., min_length=32)
    app_host: str = Field(default="127.0.0.1")
    app_port: int = Field(default=8000)
    app_debug: bool = Field(default=False)

    # ── Base de datos ─────────────────────────────────────────────────────────
    database_url: str = Field(default="sqlite:///./neonstream.db")

    # ── Clave maestra de cifrado (Fernet) ─────────────────────────────────────
    fernet_master_key: str = Field(...)

    # ── IA: Gemini ────────────────────────────────────────────────────────────
    gemini_api_key: str = Field(default="")
    gemini_model: str = Field(default="gemini-1.5-flash")

    # ── LinkedIn ──────────────────────────────────────────────────────────────
    linkedin_client_id: str = Field(default="")
    linkedin_client_secret: str = Field(default="")
    linkedin_redirect_uri: str = Field(default="http://127.0.0.1:8000/auth/linkedin/callback")
    linkedin_scopes: str = Field(default="openid,profile,email,w_member_social")

    # ── X / Twitter ───────────────────────────────────────────────────────────
    x_client_id: str = Field(default="")
    x_client_secret: str = Field(default="")
    x_redirect_uri: str = Field(default="http://127.0.0.1:8000/auth/x/callback")

    # ── Meta ──────────────────────────────────────────────────────────────────
    meta_app_id: str = Field(default="")
    meta_app_secret: str = Field(default="")
    meta_redirect_uri: str = Field(default="http://127.0.0.1:8000/auth/meta/callback")

    # ── TikTok ────────────────────────────────────────────────────────────────
    tiktok_client_key: str = Field(default="")
    tiktok_client_secret: str = Field(default="")
    tiktok_redirect_uri: str = Field(default="http://127.0.0.1:8000/auth/tiktok/callback")

    # ── Telegram ──────────────────────────────────────────────────────────────
    telegram_bot_token: str = Field(default="")
    telegram_default_chat_id: str = Field(default="")

    @field_validator("fernet_master_key")
    @classmethod
    def validate_fernet_key(cls, v: str) -> str:
        """Valida que la clave Fernet tenga el formato Base64-URL correcto."""
        import base64
        try:
            decoded = base64.urlsafe_b64decode(v.encode())
            if len(decoded) != 32:
                raise ValueError("La clave Fernet debe decodificarse a exactamente 32 bytes.")
        except Exception as exc:
            raise ValueError(f"FERNET_MASTER_KEY inválida: {exc}") from exc
        return v

    @property
    def linkedin_scopes_list(self) -> list[str]:
        return [s.strip() for s in self.linkedin_scopes.split(",")]

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton cacheado — se crea una sola vez en el ciclo de vida de la app."""
    return Settings()
