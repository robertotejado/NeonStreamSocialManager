"""
tests/test_providers.py — Tests de providers OAuth2 y publicación

Cubre con mocks (sin llamadas HTTP reales):
  • SocialMediaProvider ABC: contrato, DTOs, pipeline
  • LinkedInProvider: generate_url, handle_callback (CSRF), publish_post
  • OAuthBridge: state management thread-safe
  • Scheduler: schedule/cancel jobs
"""
from __future__ import annotations

import asyncio
import json
import threading
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest
from cryptography.fernet import Fernet


# Fixtures globales definidas en conftest.py (minimal_env, linkedin_provider, crypto)


# ══════════════════════════════════════════════════════════════════════════════
#  Tests: DTOs y clase base abstracta
# ══════════════════════════════════════════════════════════════════════════════

class TestDTOs:

    def test_post_content_full_text_con_hashtags(self):
        from providers.base import PostContent
        pc = PostContent(
            text="Hola mundo",
            hashtags=["python", "IA"],
            link_url="https://example.com",
        )
        full = pc.full_text
        assert "Hola mundo" in full
        assert "#python" in full
        assert "#IA" in full
        assert "https://example.com" in full

    def test_post_content_sin_hashtags(self):
        from providers.base import PostContent
        pc = PostContent(text="Solo texto")
        assert pc.full_text == "Solo texto"

    def test_oauth_tokens_expires_at(self):
        from providers.base import OAuthTokens
        t = OAuthTokens(access_token="tok", expires_in_seconds=3600)
        assert t.expires_at is not None
        diff = (t.expires_at - datetime.now(timezone.utc)).total_seconds()
        assert 3500 < diff < 3700

    def test_oauth_tokens_sin_expiracion(self):
        from providers.base import OAuthTokens
        t = OAuthTokens(access_token="tok")
        assert t.expires_at is None

    def test_content_validation_result_add_error(self):
        from providers.base import ContentValidationResult
        r = ContentValidationResult(is_valid=True)
        r.add_error("Texto demasiado largo")
        assert not r.is_valid
        assert "Texto demasiado largo" in r.errors

    def test_content_validation_warning_no_invalida(self):
        from providers.base import ContentValidationResult
        r = ContentValidationResult(is_valid=True)
        r.add_warning("Cerca del límite")
        assert r.is_valid
        assert len(r.warnings) == 1


class TestSocialMediaProviderABC:

    def test_no_se_puede_instanciar_directamente(self):
        from providers.base import SocialMediaProvider
        with pytest.raises(TypeError):
            SocialMediaProvider("id", "secret", "http://cb")  # type: ignore

    def test_generate_state_es_unico(self):
        from providers.base import SocialMediaProvider
        s1 = SocialMediaProvider._generate_state()
        s2 = SocialMediaProvider._generate_state()
        assert s1 != s2
        assert len(s1) > 20

    def test_verify_state_correcto(self):
        from providers.base import SocialMediaProvider
        state = "abc123xyz"
        assert SocialMediaProvider._verify_state(state, state) is True

    def test_verify_state_incorrecto(self):
        from providers.base import SocialMediaProvider
        assert SocialMediaProvider._verify_state("abc", "xyz") is False

    def test_validate_state_or_raise_lanza_con_mismatch(self, linkedin_provider):
        with pytest.raises(ValueError, match="CSRF"):
            linkedin_provider._validate_state_or_raise("estado_recibido", "estado_esperado")

    def test_validate_state_or_raise_ok(self, linkedin_provider):
        state = "estado_igual"
        linkedin_provider._validate_state_or_raise(state, state)  # No debe lanzar


# ══════════════════════════════════════════════════════════════════════════════
#  Tests: LinkedInProvider — OAuth2
# ══════════════════════════════════════════════════════════════════════════════

class TestLinkedInProviderOAuth:

    def test_get_authorization_url_contiene_client_id(self, linkedin_provider):
        url, state = linkedin_provider.get_authorization_url()
        assert "test_client_id" in url
        assert "linkedin.com/oauth/v2/authorization" in url
        assert state in url
        assert len(state) > 20

    def test_get_authorization_url_contiene_scopes(self, linkedin_provider):
        url, _ = linkedin_provider.get_authorization_url()
        assert "openid" in url

    def test_get_authorization_url_state_es_aleatorio(self, linkedin_provider):
        _, s1 = linkedin_provider.get_authorization_url()
        _, s2 = linkedin_provider.get_authorization_url()
        assert s1 != s2

    @pytest.mark.asyncio
    async def test_handle_callback_csrf_falla(self, linkedin_provider):
        with pytest.raises(ValueError, match="CSRF"):
            await linkedin_provider.handle_callback(
                code="some_code",
                state="state_A",
                expected_state="state_B",
            )

    @pytest.mark.asyncio
    async def test_handle_callback_exito(self, linkedin_provider):
        """Simula un intercambio de tokens exitoso con httpx mockeado."""
        fake_response = MagicMock()
        fake_response.status_code = 200
        fake_response.json.return_value = {
            "access_token":  "ya_access_token_12345",
            "refresh_token": "refresh_token_abcde",
            "expires_in":    3600,
            "scope":         "openid profile email w_member_social",
        }

        state = "estado_valido_csrf"
        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=fake_response
            )
            tokens = await linkedin_provider.handle_callback(
                code="auth_code_xyz",
                state=state,
                expected_state=state,
            )

        assert tokens.access_token == "ya_access_token_12345"
        assert tokens.refresh_token == "refresh_token_abcde"
        assert tokens.expires_in_seconds == 3600

    @pytest.mark.asyncio
    async def test_handle_callback_linkedin_devuelve_error(self, linkedin_provider):
        """LinkedIn devuelve error en el JSON del token."""
        fake_response = MagicMock()
        fake_response.status_code = 200
        fake_response.json.return_value = {
            "error": "invalid_grant",
            "error_description": "Authorization code expired",
        }

        state = "estado_ok"
        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=fake_response
            )
            with pytest.raises(PermissionError, match="invalid_grant"):
                await linkedin_provider.handle_callback(
                    code="expired_code", state=state, expected_state=state
                )

    @pytest.mark.asyncio
    async def test_handle_callback_http_error(self, linkedin_provider):
        """LinkedIn devuelve 401 — debe lanzar PermissionError."""
        fake_response = MagicMock()
        fake_response.status_code = 401
        fake_response.text = "Unauthorized"

        state = "estado_ok"
        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=fake_response
            )
            with pytest.raises(PermissionError):
                await linkedin_provider.handle_callback(
                    code="bad_code", state=state, expected_state=state
                )


# ══════════════════════════════════════════════════════════════════════════════
#  Tests: LinkedInProvider — Perfil y publicación
# ══════════════════════════════════════════════════════════════════════════════

class TestLinkedInProviderPublish:

    @pytest.mark.asyncio
    async def test_get_user_profile(self, linkedin_provider):
        fake_userinfo = {
            "sub":     "urn:li:person:abc123",
            "name":    "Rober Test",
            "email":   "rober@test.com",
            "picture": "https://media.licdn.com/photo.jpg",
        }
        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = fake_userinfo
        fake_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=fake_resp
            )
            profile = await linkedin_provider.get_user_profile("fake_access_token")

        assert profile.external_user_id == "urn:li:person:abc123"
        assert profile.display_name == "Rober Test"
        assert profile.email == "rober@test.com"

    def test_validate_content_ok(self, linkedin_provider):
        from providers.base import PostContent
        pc = PostContent(text="Post de prueba corto", hashtags=["test"])
        result = linkedin_provider.validate_content(pc)
        assert result.is_valid
        assert len(result.errors) == 0

    def test_validate_content_vacio_falla(self, linkedin_provider):
        from providers.base import PostContent
        pc = PostContent(text="   ")
        result = linkedin_provider.validate_content(pc)
        assert not result.is_valid
        assert any("vacío" in e.lower() or "empty" in e.lower() for e in result.errors)

    def test_validate_content_demasiado_largo(self, linkedin_provider):
        from providers.base import PostContent
        texto_largo = "x" * 3001
        pc = PostContent(text=texto_largo)
        result = linkedin_provider.validate_content(pc)
        assert not result.is_valid
        assert any("3000" in e or "límite" in e.lower() for e in result.errors)

    def test_validate_content_warning_cerca_limite(self, linkedin_provider):
        from providers.base import PostContent
        texto_largo = "x" * 2850    # 95% de 3000
        pc = PostContent(text=texto_largo)
        result = linkedin_provider.validate_content(pc)
        assert result.is_valid
        assert len(result.warnings) > 0

    def test_validate_content_demasiados_medios(self, linkedin_provider):
        from providers.base import PostContent
        pc = PostContent(text="Test", media_paths=["x.jpg"] * 10)
        result = linkedin_provider.validate_content(pc)
        assert not result.is_valid

    @pytest.mark.asyncio
    async def test_publish_post_sin_media_exito(self, linkedin_provider):
        from providers.base import PostContent

        # Mock profile
        mock_profile = MagicMock()
        mock_profile.external_user_id = "abc123"

        fake_post_resp = MagicMock()
        fake_post_resp.status_code = 201
        fake_post_resp.content = b"{}"
        fake_post_resp.json.return_value = {}
        fake_post_resp.headers = {"x-restli-id": "urn:li:ugcPost:9999"}

        content = PostContent(text="Post de prueba desde NeonStream")

        with patch.object(linkedin_provider, "get_user_profile",
                          AsyncMock(return_value=mock_profile)):
            with patch("httpx.AsyncClient") as mock_client:
                mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                    return_value=fake_post_resp
                )
                result = await linkedin_provider.publish_post("fake_token", content)

        assert result.success is True
        assert result.platform_post_id == "urn:li:ugcPost:9999"

    @pytest.mark.asyncio
    async def test_publish_post_falla_api(self, linkedin_provider):
        from providers.base import PostContent

        mock_profile = MagicMock()
        mock_profile.external_user_id = "abc123"

        fake_post_resp = MagicMock()
        fake_post_resp.status_code = 422
        fake_post_resp.content = b"error"
        fake_post_resp.text = "Unprocessable Entity"

        content = PostContent(text="Post inválido")

        with patch.object(linkedin_provider, "get_user_profile",
                          AsyncMock(return_value=mock_profile)):
            with patch("httpx.AsyncClient") as mock_client:
                mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                    return_value=fake_post_resp
                )
                result = await linkedin_provider.publish_post("fake_token", content)

        assert result.success is False
        assert "422" in result.error_message

    @pytest.mark.asyncio
    async def test_execute_publish_pipeline_valida_antes_de_publicar(self, linkedin_provider):
        """El pipeline no debe llamar a publish_post si la validación falla."""
        from providers.base import PostContent

        content = PostContent(text="")   # Vacío → falla validación

        with patch.object(linkedin_provider, "publish_post", AsyncMock()) as mock_publish:
            result = await linkedin_provider.execute_publish_pipeline("token", content)

        mock_publish.assert_not_called()
        assert result.success is False


# ══════════════════════════════════════════════════════════════════════════════
#  Tests: OAuthBridge — state store thread-safe
# ══════════════════════════════════════════════════════════════════════════════

class TestOAuthBridgeState:

    def test_store_y_get_state(self):
        from services.oauth_bridge import _SharedState
        store = _SharedState()
        store.store_state("linkedin", "abc123")
        assert store.get_state("linkedin") == "abc123"

    def test_state_crea_evento(self):
        from services.oauth_bridge import _SharedState
        store = _SharedState()
        store.store_state("linkedin", "xyz")
        assert "linkedin" in store.completion_events
        assert not store.completion_events["linkedin"].is_set()

    def test_set_result_activa_evento(self):
        from services.oauth_bridge import _SharedState
        store = _SharedState()
        store.store_state("linkedin", "state")
        store.set_result("linkedin", {"credential_id": 1})
        assert store.completion_events["linkedin"].is_set()
        assert store.get_result("linkedin") == {"credential_id": 1}

    def test_set_error_activa_evento(self):
        from services.oauth_bridge import _SharedState
        store = _SharedState()
        store.store_state("linkedin", "state")
        store.set_error("linkedin", "acceso denegado")
        assert store.completion_events["linkedin"].is_set()
        assert store.get_error("linkedin") == "acceso denegado"

    def test_concurrencia_sin_race_condition(self):
        """Escribe y lee el state desde múltiples hilos simultáneamente."""
        from services.oauth_bridge import _SharedState
        store = _SharedState()
        errors = []

        def _writer(n):
            try:
                store.store_state(f"platform_{n}", f"state_{n}")
            except Exception as e:
                errors.append(e)

        def _reader(n):
            try:
                store.get_state(f"platform_{n}")
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(20):
            threads.append(threading.Thread(target=_writer, args=(i,)))
            threads.append(threading.Thread(target=_reader, args=(i,)))

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=2)

        assert errors == [], f"Race conditions detectadas: {errors}"


# ══════════════════════════════════════════════════════════════════════════════
#  Tests: Scheduler
# ══════════════════════════════════════════════════════════════════════════════

class TestScheduler:

    @pytest.fixture(autouse=True)
    def reset_scheduler(self):
        """Resetea el singleton; usa BackgroundScheduler en tests (no necesita event loop)."""
        import services.scheduler as sched_module
        # Sustituir temporalmente la fábrica con BackgroundScheduler para tests
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.executors.pool import ThreadPoolExecutor

        def _make_test_scheduler():
            return BackgroundScheduler(
                jobstores={"default": __import__("apscheduler.jobstores.memory",
                            fromlist=["MemoryJobStore"]).MemoryJobStore()},
                executors={"default": ThreadPoolExecutor(1)},
                job_defaults={"coalesce": True, "max_instances": 1},
            )

        sched_module._scheduler_instance = _make_test_scheduler()
        yield
        instance = sched_module._scheduler_instance
        if instance and instance.running:
            instance.shutdown(wait=False)
        sched_module._scheduler_instance = None

    def test_get_scheduler_crea_instancia(self):
        from services.scheduler import get_scheduler
        sched = get_scheduler()
        assert sched is not None

    def test_get_scheduler_singleton(self):
        from services.scheduler import get_scheduler
        s1 = get_scheduler()
        s2 = get_scheduler()
        assert s1 is s2

    def test_schedule_post_crea_job(self):
        from services.scheduler import schedule_post, cancel_post_job, get_scheduler
        sched = get_scheduler()
        sched.start()

        run_at = datetime.now(timezone.utc) + timedelta(hours=1)
        job_id = schedule_post(post_id=42, scheduled_at=run_at)

        assert job_id == "post_42"
        assert sched.get_job("post_42") is not None
        cancel_post_job(42)

    def test_cancel_post_job_existente(self):
        from services.scheduler import schedule_post, cancel_post_job, get_scheduler
        sched = get_scheduler()
        sched.start()

        run_at = datetime.now(timezone.utc) + timedelta(hours=2)
        schedule_post(post_id=99, scheduled_at=run_at)

        result = cancel_post_job(99)
        assert result is True
        assert sched.get_job("post_99") is None

    def test_cancel_post_job_inexistente(self):
        from services.scheduler import cancel_post_job, get_scheduler
        get_scheduler().start()
        result = cancel_post_job(9999)
        assert result is False

    def test_schedule_post_replace_existing(self):
        """Reprogramar un post no debe crear duplicados."""
        from services.scheduler import schedule_post, cancel_post_job, get_scheduler, list_pending_jobs
        sched = get_scheduler()
        sched.start()

        t1 = datetime.now(timezone.utc) + timedelta(hours=1)
        t2 = datetime.now(timezone.utc) + timedelta(hours=2)

        schedule_post(post_id=77, scheduled_at=t1)
        schedule_post(post_id=77, scheduled_at=t2)

        jobs = [j for j in list_pending_jobs() if j["job_id"] == "post_77"]
        assert len(jobs) == 1
        cancel_post_job(77)

    def test_list_pending_jobs_formato(self):
        from services.scheduler import schedule_post, cancel_post_job, get_scheduler, list_pending_jobs
        sched = get_scheduler()
        sched.start()

        run_at = datetime.now(timezone.utc) + timedelta(hours=3)
        schedule_post(post_id=55, scheduled_at=run_at)

        jobs = list_pending_jobs()
        assert isinstance(jobs, list)
        assert any(j["job_id"] == "post_55" for j in jobs)

        job = next(j for j in jobs if j["job_id"] == "post_55")
        assert "name" in job
        assert "next_run" in job
        cancel_post_job(55)


# ══════════════════════════════════════════════════════════════════════════════
#  Tests: Gemini AI Service (mock de la API)
# ══════════════════════════════════════════════════════════════════════════════

class TestGeminiAIService:

    @pytest.fixture
    def gemini_mock(self, monkeypatch):
        """Mockea la API de Gemini (google-genai SDK v2) para no hacer llamadas reales."""
        import services.gemini_ai as ai_module
        ai_module._gemini_instance = None

        # Respuesta base del mock
        mock_response = MagicMock()
        mock_response.candidates = [MagicMock()]
        mock_response.text = json.dumps({
            "content":         "Post de prueba generado por Gemini.",
            "hashtags":        ["ciberseguridad", "IA", "linkedin"],
            "estimated_reach": "high",
            "tone":            "professional",
        })

        # Mock del cliente async (nueva SDK: client.aio.models.generate_content)
        mock_aio_models = AsyncMock()
        mock_aio_models.generate_content = AsyncMock(return_value=mock_response)

        mock_aio = MagicMock()
        mock_aio.models = mock_aio_models

        mock_client = MagicMock()
        mock_client.aio = mock_aio

        monkeypatch.setenv("GEMINI_API_KEY", "AIza_VALID_KEY_FOR_TEST")
        from config import get_settings
        get_settings.cache_clear()
        ai_module._gemini_instance = None

        with patch("google.genai.Client", return_value=mock_client):
            svc = ai_module.GeminiAIService()
            # Exponer el mock_response para que los tests puedan cambiarlo
            svc._mock_response = mock_response
            svc._mock_aio_models = mock_aio_models
            yield svc

        ai_module._gemini_instance = None

    @pytest.mark.asyncio
    async def test_generate_post_copy(self, gemini_mock):
        result = await gemini_mock.generate_post_copy(
            topic="Ciberseguridad en entornos OT",
            platform="linkedin",
            tone="professional",
        )
        assert result.content == "Post de prueba generado por Gemini."
        assert "ciberseguridad" in result.hashtags
        assert result.estimated_reach == "high"
        assert result.character_count > 0

    @pytest.mark.asyncio
    async def test_analyze_sentiment_positivo(self, gemini_mock):
        gemini_mock._mock_aio_models.generate_content.return_value.text = json.dumps({
            "label":       "positive",
            "score":       0.92,
            "emotions":    ["joy", "trust"],
            "suggestions": [],
        })
        result = await gemini_mock.analyze_sentiment("¡Gran noticia para el sector!")
        assert result.label == "positive"
        assert result.score == pytest.approx(0.92)
        assert "joy" in result.emotions

    @pytest.mark.asyncio
    async def test_suggest_hashtags_devuelve_lista(self, gemini_mock):
        gemini_mock._mock_aio_models.generate_content.return_value.text = json.dumps(
            ["ciberseguridad", "iot", "ot", "scada", "industrialcyber"]
        )
        hashtags = await gemini_mock.suggest_hashtags("Seguridad en SCADA", "linkedin")
        assert isinstance(hashtags, list)
        assert len(hashtags) > 0
        assert all(not h.startswith("#") for h in hashtags)

    @pytest.mark.asyncio
    async def test_generate_thread_devuelve_posts(self, gemini_mock):
        gemini_mock._mock_aio_models.generate_content.return_value.text = json.dumps([
            {"index": 1, "content": "Post 1: El gancho"},
            {"index": 2, "content": "Post 2: El desarrollo"},
            {"index": 3, "content": "Post 3: El CTA"},
        ])
        posts = await gemini_mock.generate_thread("IA en ciberseguridad", "x_twitter", num_posts=3)
        assert len(posts) == 3
        assert posts[0].index == 1
        assert posts[2].index == 3

    def test_is_gemini_available_sin_key(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "AIza_TU_API_KEY_AQUI")
        from config import get_settings
        get_settings.cache_clear()
        from services.gemini_ai import is_gemini_available
        assert is_gemini_available() is False

    def test_extract_json_con_bloque_markdown(self):
        from services.gemini_ai import GeminiAIService
        text = '```json\n{"key": "value"}\n```'
        result = GeminiAIService._extract_json(text)
        assert result == {"key": "value"}

    def test_extract_json_directo(self):
        from services.gemini_ai import GeminiAIService
        result = GeminiAIService._extract_json('{"a": 1, "b": [1, 2]}')
        assert result["a"] == 1
        assert result["b"] == [1, 2]
