"""
tests/test_crypto_and_models.py — Tests del core de seguridad

Cubre:
  • CryptoService: cifrado, descifrado, valores opcionales, clave inválida
  • EncryptedString TypeDecorator: round-trip en DB (SQLite en memoria)
  • SocialCredential: que los tokens NUNCA se almacenan en texto plano
"""
from __future__ import annotations

import os
import pytest
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def patch_env(monkeypatch):
    """Inyecta variables de entorno mínimas para que Settings no falle."""
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("FERNET_MASTER_KEY", key)
    monkeypatch.setenv("APP_SECRET_KEY", "a" * 32)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    # Invalidar el singleton cacheado entre tests
    from config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def crypto():
    """Instancia fresca del CryptoService para cada test."""
    # Resetear el singleton global del módulo
    import services.crypto as crypto_module
    crypto_module._crypto_instance = None
    svc = crypto_module.get_crypto()
    yield svc
    crypto_module._crypto_instance = None


@pytest.fixture
def db_session():
    """Sesión SQLAlchemy en memoria con el schema completo."""
    from models.database import Base
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


# ══════════════════════════════════════════════════════════════════════════════
#  Tests: CryptoService
# ══════════════════════════════════════════════════════════════════════════════

class TestCryptoService:

    def test_encrypt_returns_bytes(self, crypto):
        result = crypto.encrypt("mi_token_secreto")
        assert isinstance(result, bytes)

    def test_encrypt_decrypt_roundtrip(self, crypto):
        plaintext = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.ejemplo_token"
        ciphertext = crypto.encrypt(plaintext)
        assert crypto.decrypt(ciphertext) == plaintext

    def test_ciphertext_is_not_plaintext(self, crypto):
        """Verificar que el token NO aparece en texto claro en el ciphertext."""
        plaintext = "super_secret_access_token_12345"
        ciphertext = crypto.encrypt(plaintext)
        assert plaintext.encode() not in ciphertext, (
            "¡CRÍTICO! El plaintext aparece sin cifrar en el ciphertext."
        )

    def test_different_encryptions_are_unique(self, crypto):
        """Fernet usa IV aleatorio: dos cifrados del mismo texto dan resultados distintos."""
        token = "mismo_token"
        c1 = crypto.encrypt(token)
        c2 = crypto.encrypt(token)
        assert c1 != c2, "Dos cifrados del mismo texto no deberían producir el mismo ciphertext."
        # Pero ambos deben descifrarse al mismo valor
        assert crypto.decrypt(c1) == crypto.decrypt(c2) == token

    def test_empty_string_raises(self, crypto):
        with pytest.raises(ValueError, match="vacía"):
            crypto.encrypt("")

    def test_empty_bytes_raises(self, crypto):
        with pytest.raises(ValueError, match="vacíos"):
            crypto.decrypt(b"")

    def test_tampered_ciphertext_raises(self, crypto):
        ciphertext = crypto.encrypt("token_valido")
        tampered = ciphertext[:-4] + b"XXXX"
        with pytest.raises(InvalidToken):
            crypto.decrypt(tampered)

    def test_wrong_key_raises(self, monkeypatch, crypto):
        """Un ciphertext cifrado con una clave no puede descifrarse con otra."""
        original_ciphertext = crypto.encrypt("token_original")

        # Crear un nuevo CryptoService con una clave diferente
        new_key = Fernet.generate_key().decode()
        monkeypatch.setenv("FERNET_MASTER_KEY", new_key)
        from config import get_settings
        get_settings.cache_clear()
        import services.crypto as crypto_module
        crypto_module._crypto_instance = None
        new_crypto = crypto_module.get_crypto()

        with pytest.raises(InvalidToken):
            new_crypto.decrypt(original_ciphertext)

    def test_encrypt_optional_none(self, crypto):
        assert crypto.encrypt_optional(None) is None

    def test_decrypt_optional_none(self, crypto):
        assert crypto.decrypt_optional(None) is None

    def test_generate_key_format(self):
        from services.crypto import CryptoService
        import base64
        key = CryptoService.generate_key()
        assert isinstance(key, str)
        decoded = base64.urlsafe_b64decode(key.encode())
        assert len(decoded) == 32, "Una clave Fernet debe decodificarse a exactamente 32 bytes."

    def test_long_token(self, crypto):
        """Tokens JWT reales son largos — verificar que funcionan."""
        long_token = "Bearer " + "x" * 2048
        assert crypto.decrypt(crypto.encrypt(long_token)) == long_token


# ══════════════════════════════════════════════════════════════════════════════
#  Tests: EncryptedString TypeDecorator (integración con SQLite)
# ══════════════════════════════════════════════════════════════════════════════

class TestEncryptedStringInDB:

    def test_tokens_stored_as_bytes_not_plaintext(self, db_session):
        """
        Verifica que en SQLite los tokens se almacenan como bytes cifrados,
        nunca como texto plano.
        """
        from models.database import SocialCredential, SocialPlatform
        from sqlalchemy import text

        plaintext_token = "access_token_en_texto_claro_12345"

        cred = SocialCredential(
            platform=SocialPlatform.LINKEDIN,
            external_user_id="urn:li:person:test123",
            username="test_user",
            access_token=plaintext_token,  # TypeDecorator cifra al escribir
        )
        db_session.add(cred)
        db_session.commit()

        # Leer directamente de SQLite sin pasar por SQLAlchemy ORM
        raw = db_session.execute(
            text("SELECT access_token FROM social_credentials WHERE id = :id"),
            {"id": cred.id}
        ).fetchone()

        raw_value = raw[0]
        assert raw_value is not None
        # El valor raw debe ser bytes, NO el string original
        if isinstance(raw_value, str):
            assert plaintext_token not in raw_value, (
                "¡CRÍTICO! El access_token está almacenado en texto plano en la BD."
            )
        elif isinstance(raw_value, bytes):
            assert plaintext_token.encode() not in raw_value, (
                "¡CRÍTICO! El access_token está almacenado en texto plano (bytes) en la BD."
            )

    def test_orm_decrypts_on_read(self, db_session):
        """El ORM debe devolver el token descifrado al leer desde DB."""
        from models.database import SocialCredential, SocialPlatform

        plaintext_token = "ya_oauth2_bearer_xxxxyyyyzzzz"

        cred = SocialCredential(
            platform=SocialPlatform.LINKEDIN,
            external_user_id="urn:li:person:decrypttest",
            username="decrypt_test",
            access_token=plaintext_token,
        )
        db_session.add(cred)
        db_session.commit()
        db_session.expire(cred)  # Forzar recarga desde DB

        fresh = db_session.query(SocialCredential).filter_by(id=cred.id).first()
        assert fresh.access_token == plaintext_token, (
            "El ORM debería devolver el token descifrado."
        )

    def test_null_token_stays_null(self, db_session):
        """Un token nulo debe seguir siendo nulo tras el round-trip."""
        from models.database import SocialCredential, SocialPlatform

        cred = SocialCredential(
            platform=SocialPlatform.X_TWITTER,
            external_user_id="twitter_no_token",
            username="no_token_user",
            access_token=None,
        )
        db_session.add(cred)
        db_session.commit()
        db_session.expire(cred)

        fresh = db_session.query(SocialCredential).filter_by(id=cred.id).first()
        assert fresh.access_token is None

    def test_refresh_token_also_encrypted(self, db_session):
        """El refresh_token también debe cifrarse."""
        from models.database import SocialCredential, SocialPlatform
        from sqlalchemy import text

        refresh = "refresh_token_secreto_abcdef"

        cred = SocialCredential(
            platform=SocialPlatform.LINKEDIN,
            external_user_id="urn:li:person:refreshtest",
            username="refresh_user",
            refresh_token=refresh,
        )
        db_session.add(cred)
        db_session.commit()

        raw = db_session.execute(
            text("SELECT refresh_token FROM social_credentials WHERE id = :id"),
            {"id": cred.id}
        ).fetchone()[0]

        if isinstance(raw, (str, bytes)):
            raw_str = raw if isinstance(raw, str) else raw.decode("latin-1", errors="replace")
            assert refresh not in raw_str, (
                "¡CRÍTICO! El refresh_token está en texto plano en la BD."
            )
