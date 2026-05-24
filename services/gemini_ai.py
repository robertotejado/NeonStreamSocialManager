"""
services/gemini_ai.py — Integración con Google Gemini API

Usa la SDK oficial `google-genai` (v2+), sustituta de la deprecada
`google-generativeai`. La interfaz pública (métodos y DTOs) es idéntica
a la versión anterior — no hay cambios en ninguna vista ni test.

Módulos:
  • generate_post_copy()   → borrador completo con hashtags
  • suggest_hashtags()     → lista de hashtags relevantes
  • analyze_sentiment()    → positivo / negativo / neutro + emociones
  • generate_thread()      → hilo multi-post
  • rewrite_post()         → reescribir con tono distinto
  • improve_post()         → sugerencias de mejora accionables
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from config import get_settings

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  DTOs (sin cambios respecto a la versión anterior)
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class GeneratedPost:
    content: str
    hashtags: list[str] = field(default_factory=list)
    estimated_reach: str = "medium"
    tone: str = "professional"
    character_count: int = 0

    def __post_init__(self):
        self.character_count = len(self.content)


@dataclass
class SentimentResult:
    label: str
    score: float
    emotions: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


@dataclass
class ThreadPost:
    index: int
    content: str
    character_count: int = 0

    def __post_init__(self):
        self.character_count = len(self.content)


@dataclass
class ImprovementSuggestion:
    category: str
    issue: str
    suggestion: str
    priority: str


# ══════════════════════════════════════════════════════════════════════════════
#  Servicio
# ══════════════════════════════════════════════════════════════════════════════

class GeminiAIService:
    """
    Wrapper de Google Gemini (google-genai SDK v2+).
    Singleton — usar get_gemini_service() para obtener la instancia.
    """

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.gemini_api_key or settings.gemini_api_key.startswith("AIza_TU"):
            raise ValueError(
                "GEMINI_API_KEY no configurada. "
                "Añádela al .env para usar el AI Content Lab."
            )
        # Nueva SDK: cliente por API key
        from google import genai
        self._client = genai.Client(api_key=settings.gemini_api_key)
        self._model  = settings.gemini_model
        logger.info("GeminiAIService listo (google-genai SDK v2+, modelo=%s)", self._model)

    # ── Helper interno ────────────────────────────────────────────────────────

    async def _generate(self, prompt: str) -> str:
        """Llama a Gemini de forma async y devuelve el texto de la respuesta."""
        from google.genai import types as gtypes

        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=prompt,
            config=gtypes.GenerateContentConfig(
                temperature=0.85,
                top_p=0.92,
                top_k=40,
                max_output_tokens=2048,
            ),
        )
        if not response.candidates:
            raise RuntimeError(
                "Gemini no devolvió candidatos — posible bloqueo de seguridad."
            )
        return response.text.strip()

    @staticmethod
    def _extract_json(text: str) -> dict | list:
        """Extrae JSON de una respuesta que puede incluir texto o bloques markdown."""
        match = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
        if match:
            text = match.group(1).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = min(
                text.find("{") if "{" in text else len(text),
                text.find("[") if "[" in text else len(text),
            )
            if start < len(text):
                end = max(text.rfind("}") + 1, text.rfind("]") + 1)
                return json.loads(text[start:end])
            raise ValueError(f"No se pudo extraer JSON: {text[:200]}")

    # ── API pública ───────────────────────────────────────────────────────────

    async def generate_post_copy(
        self,
        topic: str,
        platform: str,
        tone: str = "professional",
        language: str = "español",
        context: Optional[str] = None,
        max_length: Optional[int] = None,
    ) -> GeneratedPost:
        limits = {
            "linkedin": 3000, "x_twitter": 280,
            "instagram": 2200, "facebook": 63206, "tiktok": 2200,
        }
        char_limit = max_length or limits.get(platform.lower(), 1000)
        hints = {
            "linkedin":  "audiencia profesional, B2B, párrafos cortos",
            "x_twitter": f"máximo {char_limit} caracteres, directo, gancho inicial",
            "instagram": "visual y emotivo, emojis con moderación, CTA claro",
            "facebook":  "conversacional, storytelling",
        }
        hint    = hints.get(platform.lower(), "estilo neutral")
        ctx_blk = f"\nContexto adicional: {context}" if context else ""

        prompt = f"""Eres un experto en marketing de contenidos y social media.
Genera un post en {language} para {platform.upper()} sobre:

TEMA: {topic}
TONO: {tone}
PLATAFORMA: {platform.upper()} ({hint})
LÍMITE: máximo {char_limit} caracteres en el texto del post{ctx_blk}

Responde ÚNICAMENTE con un JSON (sin texto adicional):
{{
  "content": "texto del post sin hashtags",
  "hashtags": ["hashtag1", "hashtag2", "hashtag3"],
  "estimated_reach": "low|medium|high",
  "tone": "{tone}"
}}

Reglas:
- content SIN hashtags (van en el array separado)
- Máximo 5 hashtags relevantes, sin el símbolo #
- estimated_reach refleja el potencial viral real"""

        data = self._extract_json(await self._generate(prompt))
        return GeneratedPost(
            content=data.get("content", ""),
            hashtags=data.get("hashtags", []),
            estimated_reach=data.get("estimated_reach", "medium"),
            tone=data.get("tone", tone),
        )

    async def suggest_hashtags(
        self,
        content: str,
        platform: str,
        count: int = 10,
        language: str = "español",
    ) -> list[str]:
        prompt = f"""Analiza el siguiente texto para {platform.upper()} y sugiere
exactamente {count} hashtags relevantes en {language} e inglés mezclados.

TEXTO: {content}

Responde ÚNICAMENTE con un JSON array de strings, sin el símbolo #.
Ejemplo: ["marketing", "socialmedia", "branding"]

Criterios:
- Mezcla hashtags populares (alcance) con de nicho (relevancia)
- Prioriza los que usan realmente los profesionales del sector
- Sin espacios dentro de los hashtags"""

        result = self._extract_json(await self._generate(prompt))
        if isinstance(result, list):
            return [h.lstrip("#").strip() for h in result[:count]]
        return []

    async def analyze_sentiment(self, content: str) -> SentimentResult:
        prompt = f"""Analiza el sentimiento del siguiente texto de redes sociales:

TEXTO: {content}

Responde ÚNICAMENTE con JSON:
{{
  "label": "positive|negative|neutral",
  "score": 0.0,
  "emotions": ["emoción1", "emoción2"],
  "suggestions": ["sugerencia breve si aplica"]
}}

- score: confianza de 0.0 a 1.0
- emotions: 1-3 emociones (joy, trust, fear, professional, inspiring…)
- suggestions: 0-2 mejoras concretas (vacío si el texto está bien)"""

        data = self._extract_json(await self._generate(prompt))
        return SentimentResult(
            label=data.get("label", "neutral"),
            score=float(data.get("score", 0.5)),
            emotions=data.get("emotions", []),
            suggestions=data.get("suggestions", []),
        )

    async def generate_thread(
        self,
        topic: str,
        platform: str,
        num_posts: int = 5,
        tone: str = "educational",
        language: str = "español",
    ) -> list[ThreadPost]:
        num_posts = max(2, min(10, num_posts))
        limits    = {"x_twitter": 280, "linkedin": 1300}
        char_limit = limits.get(platform.lower(), 500)

        prompt = f"""Crea un hilo de exactamente {num_posts} posts en {language}
para {platform.upper()} sobre: "{topic}"

Tono: {tone} | Límite por post: {char_limit} caracteres

Reglas:
- Post 1: gancho que invite a seguir leyendo
- Cada post con sentido propio pero que invite al siguiente
- Último post: CTA claro
- NO numeres el texto manualmente (sin "1/5")

Responde ÚNICAMENTE con un JSON array:
[
  {{"index": 1, "content": "texto post 1"}},
  {{"index": 2, "content": "texto post 2"}}
]"""

        data = self._extract_json(await self._generate(prompt))
        if not isinstance(data, list):
            raise ValueError("Gemini no devolvió un array de posts.")
        return [
            ThreadPost(index=item.get("index", i + 1), content=item.get("content", ""))
            for i, item in enumerate(data)
        ]

    async def rewrite_post(
        self,
        original: str,
        target_tone: str,
        platform: str,
        language: str = "español",
    ) -> GeneratedPost:
        limits    = {"linkedin": 3000, "x_twitter": 280, "instagram": 2200}
        char_limit = limits.get(platform.lower(), 1000)

        prompt = f"""Reescribe el siguiente post para {platform.upper()} en {language}
manteniendo la idea central pero con tono {target_tone}.

POST ORIGINAL:
{original}

Máximo {char_limit} caracteres. Responde ÚNICAMENTE con JSON:
{{
  "content": "post reescrito",
  "hashtags": ["hashtag1", "hashtag2"],
  "tone": "{target_tone}"
}}"""

        data = self._extract_json(await self._generate(prompt))
        return GeneratedPost(
            content=data.get("content", original),
            hashtags=data.get("hashtags", []),
            tone=target_tone,
        )

    async def improve_post(self, content: str, platform: str) -> list[ImprovementSuggestion]:
        prompt = f"""Actúa como consultor de social media. Analiza este post para {platform.upper()}
y da sugerencias concretas de mejora.

POST: {content}

Responde ÚNICAMENTE con un JSON array (máx 5 sugerencias):
[
  {{
    "category": "clarity|engagement|seo|tone|length|hook|cta",
    "issue": "descripción breve del problema",
    "suggestion": "qué hacer exactamente",
    "priority": "high|medium|low"
  }}
]

Si el post está bien, devuelve []. Sé específico, no genérico."""

        data = self._extract_json(await self._generate(prompt))
        if not isinstance(data, list):
            return []
        return [
            ImprovementSuggestion(
                category=item.get("category", "general"),
                issue=item.get("issue", ""),
                suggestion=item.get("suggestion", ""),
                priority=item.get("priority", "medium"),
            )
            for item in data
        ]


# ── Singleton ─────────────────────────────────────────────────────────────────

_gemini_instance: GeminiAIService | None = None


def get_gemini_service() -> GeminiAIService:
    global _gemini_instance
    if _gemini_instance is None:
        _gemini_instance = GeminiAIService()
    return _gemini_instance


def is_gemini_available() -> bool:
    try:
        s = get_settings()
        return bool(s.gemini_api_key and not s.gemini_api_key.startswith("AIza_TU"))
    except Exception:
        return False
