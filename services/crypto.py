"""
services/crypto.py — Capa de cifrado de tokens OAuth2

Usa Fernet (AES-128-CBC + HMAC-SHA256) de la librería `cryptography`.
Fernet garantiza:
  • Confidencialidad  → cifrado simétrico AES-128 en modo CBC con IV aleatorio.
  • Integridad        → HMAC-SHA256 sobre el ciphertext (encrypt-then-MAC).
  • Autenticidad      → el token incluye timestamp de creación.

Flujo:
  plaintext  ──encrypt()──>  token_bytes (base64-url)  ──> DB (columna BLOB)
  token_bytes ──decrypt()──>  plaintext

Soporte de rotación:
  Si en el futuro necesitas re-cifrar con una nueva clave, MultiFernet intenta
  descifrar con todas las claves en orden y cifra siempre con la primera
  (la más reciente). Añade nuevas claves al inicio de FERNET_KEY_CHAIN en .env.
"""
import base64
import logging
from typing import Optional

from cryptography.fernet import Fernet, MultiFernet, InvalidToken

from config import get_settings

logger = logging.getLogger(__name__)


class CryptoService:
    """
    Servicio singleton de cifrado/descifrado.

    Uso:
        crypto = CryptoService()
        ciphertext = crypto.encrypt("mi_access_token")
        plaintext  = crypto.decrypt(ciphertext)      # → "mi_access_token"
    """

    def __init__(self) -> None:
        settings = get_settings()
        # Clave principal. En producción puedes pasar varias separadas por coma
        # para soportar rotación de claves (MultiFernet).
        primary_key = settings.fernet_master_key.encode()
        self._fernet = MultiFernet([Fernet(primary_key)])

    # ── Operaciones públicas ──────────────────────────────────────────────────

    def encrypt(self, plaintext: str) -> bytes:
        """
        Cifra una cadena de texto y devuelve los bytes cifrados.

        Args:
            plaintext: El token o secreto en texto claro.

        Returns:
            Bytes Fernet (base64-url). Seguros para almacenar en BLOB/TEXT SQL.

        Raises:
            ValueError: Si el plaintext está vacío.
        """
        if not plaintext:
            raise ValueError("No se puede cifrar una cadena vacía.")
        token_bytes = self._fernet.encrypt(plaintext.encode("utf-8"))
        logger.debug("Token cifrado correctamente (longitud ciphertext: %d bytes).", len(token_bytes))
        return token_bytes

    def decrypt(self, ciphertext: bytes) -> str:
        """
        Descifra bytes Fernet y devuelve el texto claro.

        Args:
            ciphertext: Los bytes almacenados en la base de datos.

        Returns:
            El token en texto claro.

        Raises:
            InvalidToken: Si el ciphertext está corrompido o la clave es incorrecta.
        """
        if not ciphertext:
            raise ValueError("No se puede descifrar datos vacíos.")
        try:
            plaintext_bytes = self._fernet.decrypt(ciphertext)
            return plaintext_bytes.decode("utf-8")
        except InvalidToken as exc:
            logger.error("Fallo al descifrar token: clave incorrecta o datos corrompidos.")
            raise InvalidToken("Descifrado fallido: clave inválida o token corrompido.") from exc

    def encrypt_optional(self, plaintext: Optional[str]) -> Optional[bytes]:
        """Versión segura para valores opcionales (devuelve None si la entrada es None)."""
        return self.encrypt(plaintext) if plaintext else None

    def decrypt_optional(self, ciphertext: Optional[bytes]) -> Optional[str]:
        """Versión segura para valores opcionales (devuelve None si la entrada es None)."""
        return self.decrypt(ciphertext) if ciphertext else None

    @staticmethod
    def generate_key() -> str:
        """
        Genera una nueva clave Fernet lista para pegar en .env.
        Útil para el script de setup o para rotación de claves.

        Returns:
            String base64-url de 44 caracteres.
        """
        return Fernet.generate_key().decode()

    @staticmethod
    def rotate_keys(old_key: str, new_key: str, ciphertext: bytes) -> bytes:
        """
        Re-cifra un ciphertext de una clave antigua a una nueva.
        Útil durante el proceso de rotación de claves en producción.

        Args:
            old_key: La clave Fernet con la que estaba cifrado.
            new_key: La nueva clave Fernet.
            ciphertext: El ciphertext almacenado en DB.

        Returns:
            Ciphertext re-cifrado con new_key.
        """
        rotator = MultiFernet([Fernet(new_key.encode()), Fernet(old_key.encode())])
        return rotator.rotate(ciphertext)


# Instancia global del servicio (lazy-init en primer uso)
_crypto_instance: Optional[CryptoService] = None


def get_crypto() -> CryptoService:
    """Devuelve la instancia singleton del servicio de criptografía."""
    global _crypto_instance
    if _crypto_instance is None:
        _crypto_instance = CryptoService()
    return _crypto_instance
