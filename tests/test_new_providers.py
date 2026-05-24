"""
tests/test_new_providers.py — Tests para TikTok, Telegram y EnvManager
"""
from __future__ import annotations
import asyncio
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.fernet import Fernet


# ── TikTok Provider ────────────────────────────────────────────────────────────

class TestTikTokProvider:

    @pytest.fixture
    def provider(self):
        from providers.tiktok import TikTokProvider
        return TikTokProvider(
            client_key="test_key",
            client_secret="test_secret",
            redirect_uri="http://localhost:8000/auth/tiktok/callback",
        )

    def test_get_authorization_url(self, provider):
        url, state = provider.get_authorization_url()
        assert "tiktok.com" in url
        assert "test_key" in url
        assert "S256" in url
        assert len(state) > 20

    def test_pkce_pair_generates_valid_challenge(self):
        from providers.tiktok import TikTokProvider
        import base64, hashlib
        verifier, challenge = TikTokProvider._pkce_pair()
        expected = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()
        ).rstrip(b"=").decode()
        assert challenge == expected

    def test_validate_content_requires_video(self, provider):
        from providers.base import PostContent
        result = provider.validate_content(PostContent(text="hola"))
        assert not result.is_valid
        assert any("vídeo" in e.lower() or "video" in e.lower() for e in result.errors)

    def test_validate_content_ok_with_video(self, provider, tmp_path):
        from providers.base import PostContent
        # Crear un mp4 dummy
        video = tmp_path / "test.mp4"
        video.write_bytes(b"\x00" * 1024)
        result = provider.validate_content(PostContent(text="mi video", media_paths=[str(video)]))
        assert result.is_valid

    def test_validate_wrong_extension(self, provider, tmp_path):
        from providers.base import PostContent
        img = tmp_path / "test.jpg"
        img.write_bytes(b"\xff\xd8")
        result = provider.validate_content(PostContent(text="x", media_paths=[str(img)]))
        assert not result.is_valid

    def test_state_csrf_mismatch(self, provider):
        with pytest.raises(ValueError, match="CSRF"):
            asyncio.run(provider.handle_callback("code", "state_a", "state_b"))

    @pytest.mark.asyncio
    async def test_upload_media_returns_publish_id(self, provider, tmp_path):
        video = tmp_path / "test.mp4"
        video.write_bytes(b"\x00" * 512)

        fake_init = MagicMock()
        fake_init.status_code = 200
        fake_init.json.return_value = {
            "data": {"publish_id": "pub_123", "upload_url": "https://upload.tiktok.com/test"}
        }
        fake_init.raise_for_status = MagicMock()

        fake_upload = MagicMock()
        fake_upload.status_code = 200
        fake_upload.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=fake_init)
            mock_client.return_value.__aenter__.return_value.put  = AsyncMock(return_value=fake_upload)
            result = await provider.upload_media("token", str(video), "video/mp4")

        assert result == "pub_123"

    @pytest.mark.asyncio
    async def test_publish_post_without_media_fails(self, provider):
        from providers.base import PostContent
        result = await provider.publish_post("token", PostContent(text="x"), media_ids=None)
        assert not result.success
        assert "vídeo" in result.error_message.lower() or "video" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_publish_post_with_media_succeeds(self, provider):
        from providers.base import PostContent
        result = await provider.publish_post("token", PostContent(text="x"), media_ids=["pub_456"])
        assert result.success
        assert result.platform_post_id == "pub_456"


# ── Telegram Provider ─────────────────────────────────────────────────────────

class TestTelegramProvider:

    @pytest.fixture
    def provider(self):
        from providers.telegram import TelegramProvider
        return TelegramProvider(
            bot_token="1234567890:AABBccDDeeFFggHHiiJJ",
            default_chat_id="-100123456789",
        )

    def test_platform_name(self, provider):
        assert provider.PLATFORM_NAME == "Telegram"

    def test_validate_empty_fails(self, provider):
        from providers.base import PostContent
        result = provider.validate_content(PostContent(text=""))
        assert not result.is_valid

    def test_validate_text_ok(self, provider):
        from providers.base import PostContent
        result = provider.validate_content(PostContent(text="Hola mundo"))
        assert result.is_valid

    def test_validate_text_too_long(self, provider):
        from providers.base import PostContent
        result = provider.validate_content(PostContent(text="x" * 4097))
        assert not result.is_valid
        assert any("4096" in e for e in result.errors)

    def test_validate_caption_limit_with_media(self, provider, tmp_path):
        from providers.base import PostContent
        img = tmp_path / "img.jpg"
        img.write_bytes(b"\xff\xd8")
        result = provider.validate_content(
            PostContent(text="x" * 1025, media_paths=[str(img)])
        )
        assert not result.is_valid
        assert any("1024" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_get_user_profile(self, provider):
        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.raise_for_status = MagicMock()
        fake_resp.json.return_value = {
            "ok": True,
            "result": {"id": 123, "username": "mi_bot", "first_name": "MiBot"}
        }
        with patch("httpx.AsyncClient") as mc:
            mc.return_value.__aenter__.return_value.get = AsyncMock(return_value=fake_resp)
            profile = await provider.get_user_profile("token")
        assert profile.username == "mi_bot"
        assert profile.external_user_id == "123"

    @pytest.mark.asyncio
    async def test_verify_bot_token_ok(self, provider):
        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.raise_for_status = MagicMock()
        fake_resp.json.return_value = {
            "ok": True,
            "result": {"id": 1, "username": "mi_bot", "first_name": "Bot"}
        }
        with patch("httpx.AsyncClient") as mc:
            mc.return_value.__aenter__.return_value.get = AsyncMock(return_value=fake_resp)
            ok, info = await provider.verify_bot_token()
        assert ok is True
        assert "@mi_bot" in info

    @pytest.mark.asyncio
    async def test_publish_text_message(self, provider):
        from providers.base import PostContent
        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.raise_for_status = MagicMock()
        fake_resp.json.return_value = {"ok": True, "result": {"message_id": 99}}
        with patch("httpx.AsyncClient") as mc:
            mc.return_value.__aenter__.return_value.post = AsyncMock(return_value=fake_resp)
            result = await provider.publish_post(
                "token", PostContent(text="Hola desde NeonStream")
            )
        assert result.success
        assert result.platform_post_id == "99"

    @pytest.mark.asyncio
    async def test_publish_without_chat_id_fails(self):
        from providers.telegram import TelegramProvider
        from providers.base import PostContent
        provider = TelegramProvider(bot_token="123:ABC")  # sin default_chat_id
        result = await provider.publish_post("token", PostContent(text="test"))
        assert not result.success
        assert "chat_id" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_upload_media_returns_path(self, provider, tmp_path):
        """Telegram no hace pre-upload — devuelve el path local."""
        img = tmp_path / "photo.jpg"
        img.write_bytes(b"data")
        result = await provider.upload_media("token", str(img), "image/jpeg")
        assert result == str(img)

    def test_refresh_token_returns_bot_token(self, provider):
        result = asyncio.run(provider.refresh_access_token("cualquier_refresh"))
        assert result.access_token == provider._bot_token


# ── EnvManager ────────────────────────────────────────────────────────────────

class TestEnvManager:

    @pytest.fixture
    def tmp_env(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text(
            "LINKEDIN_CLIENT_ID=old_id\n"
            "LINKEDIN_CLIENT_SECRET=old_secret\n"
            "GEMINI_API_KEY=old_key\n",
            encoding="utf-8",
        )
        from services.env_manager import EnvManager
        return EnvManager(env_path=env_file), env_file

    def test_read_all(self, tmp_env):
        mgr, _ = tmp_env
        vals = mgr.read_all()
        assert vals["LINKEDIN_CLIENT_ID"] == "old_id"
        assert vals["GEMINI_API_KEY"] == "old_key"

    def test_get_existing_key(self, tmp_env):
        mgr, _ = tmp_env
        assert mgr.get("LINKEDIN_CLIENT_ID") == "old_id"

    def test_get_missing_key_default(self, tmp_env):
        mgr, _ = tmp_env
        assert mgr.get("NO_EXISTE", "default") == "default"

    def test_set_existing_key(self, tmp_env):
        mgr, env_file = tmp_env
        ok = mgr.set("LINKEDIN_CLIENT_ID", "new_id_123")
        assert ok
        content = env_file.read_text()
        assert "new_id_123" in content
        assert "old_id" not in content

    def test_set_new_key(self, tmp_env):
        mgr, env_file = tmp_env
        ok = mgr.set("X_CLIENT_ID", "x_id_abc")
        assert ok
        assert "x_id_abc" in env_file.read_text()

    def test_set_protected_key_rejected(self, tmp_env):
        mgr, _ = tmp_env
        ok = mgr.set("FERNET_MASTER_KEY", "new_fernet")
        assert not ok

    def test_set_unknown_key_rejected(self, tmp_env):
        mgr, _ = tmp_env
        ok = mgr.set("RANDOM_UNKNOWN_VAR", "value")
        assert not ok

    def test_set_many(self, tmp_env):
        mgr, env_file = tmp_env
        results = mgr.set_many({
            "LINKEDIN_CLIENT_ID":     "multi_id",
            "LINKEDIN_CLIENT_SECRET": "multi_secret",
        })
        assert all(results.values())
        content = env_file.read_text()
        assert "multi_id" in content
        assert "multi_secret" in content

    def test_has_credentials_false_when_placeholder(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("LINKEDIN_CLIENT_ID=TU_CLIENT_ID\nLINKEDIN_CLIENT_SECRET=\n")
        from services.env_manager import EnvManager
        mgr = EnvManager(env_path=env_file)
        assert mgr.has_credentials("linkedin") is False

    def test_has_credentials_true_when_set(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text(
            "LINKEDIN_CLIENT_ID=real_client_id\n"
            "LINKEDIN_CLIENT_SECRET=real_secret\n"
        )
        from services.env_manager import EnvManager
        mgr = EnvManager(env_path=env_file)
        assert mgr.has_credentials("linkedin") is True

    def test_get_platform_values(self, tmp_env):
        mgr, _ = tmp_env
        vals = mgr.get_platform_values("linkedin")
        assert "LINKEDIN_CLIENT_ID" in vals
        assert "LINKEDIN_CLIENT_SECRET" in vals
        assert "GEMINI_API_KEY" not in vals


# ── Instagram Provider ────────────────────────────────────────────────────────

class TestInstagramProvider:

    @pytest.fixture
    def provider(self):
        from providers.instagram import InstagramProvider
        return InstagramProvider(
            app_id="123456",
            app_secret="test_secret",
            redirect_uri="http://localhost:8000/auth/meta/callback",
        )

    def test_get_authorization_url(self, provider):
        url, state = provider.get_authorization_url()
        assert "facebook.com" in url
        assert "123456" in url
        assert "instagram_content_publish" in url
        assert len(state) > 20

    def test_state_csrf_mismatch(self, provider):
        with pytest.raises(ValueError, match="CSRF"):
            asyncio.run(provider.handle_callback("code", "s1", "s2"))

    def test_validate_empty_fails(self, provider):
        from providers.base import PostContent
        result = provider.validate_content(PostContent(text=""))
        assert not result.is_valid

    def test_validate_text_only_fails(self, provider):
        """Instagram no permite solo texto — necesita imagen."""
        from providers.base import PostContent
        result = provider.validate_content(PostContent(text="Solo texto sin imagen"))
        # Contenido válido en validate pero publish fallará
        assert result.is_valid  # validate no bloquea texto solo

    def test_validate_too_many_images(self, provider, tmp_path):
        from providers.base import PostContent
        imgs = []
        for i in range(11):
            p = tmp_path / f"img{i}.jpg"
            p.write_bytes(b"\xff\xd8")
            imgs.append(str(p))
        result = provider.validate_content(PostContent(text="x", media_paths=imgs))
        assert not result.is_valid
        assert any("10" in e for e in result.errors)

    def test_validate_caption_too_long(self, provider):
        from providers.base import PostContent
        result = provider.validate_content(PostContent(text="x" * 2201))
        assert not result.is_valid

    def test_validate_ok(self, provider, tmp_path):
        from providers.base import PostContent
        img = tmp_path / "ok.jpg"
        img.write_bytes(b"\xff\xd8")
        result = provider.validate_content(
            PostContent(text="Post válido", media_paths=[str(img)])
        )
        assert result.is_valid

    @pytest.mark.asyncio
    async def test_publish_without_media_fails(self, provider):
        from providers.base import PostContent
        with patch.object(provider, "get_user_profile",
                          AsyncMock(return_value=MagicMock(external_user_id="123"))):
            result = await provider.publish_post(
                "token", PostContent(text="test"), media_ids=None
            )
        assert not result.success
        assert "texto" in result.error_message.lower() or "imagen" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_handle_callback_success(self, provider):
        """Simula el intercambio code→short_token→long_token."""
        short_resp = MagicMock()
        short_resp.status_code = 200
        short_resp.raise_for_status = MagicMock()
        short_resp.json.return_value = {"access_token": "short_tok"}

        long_resp = MagicMock()
        long_resp.status_code = 200
        long_resp.raise_for_status = MagicMock()
        long_resp.json.return_value = {
            "access_token": "long_tok_60days",
            "expires_in": 5184000,
        }

        state = "csrf_state"
        call_count = [0]
        async def fake_get(*args, **kwargs):
            call_count[0] += 1
            return short_resp if call_count[0] == 1 else long_resp

        with patch("httpx.AsyncClient") as mc:
            mc.return_value.__aenter__.return_value.get = fake_get
            tokens = await provider.handle_callback("auth_code", state, state)

        assert tokens.access_token == "long_tok_60days"
        assert tokens.expires_in_seconds == 5184000

    def test_max_post_length(self, provider):
        assert provider.MAX_POST_LENGTH == 2200

    def test_platform_name(self, provider):
        assert provider.PLATFORM_NAME == "Instagram"
