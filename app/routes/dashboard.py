"""
app/routes/dashboard.py — Dashboard principal (stub para Fase 2)

Aquí irá el feed unificado de menciones, el panel de analytics con Plotly
y el AI Content Lab con Gemini.
"""
from fastapi import APIRouter

router = APIRouter()


@router.get("/", summary="Dashboard principal")
async def dashboard_home():
    return {
        "message": "Dashboard — Fase 2",
        "modules": [
            "Unified Inbox (menciones + mensajes)",
            "AI Content Lab (Gemini)",
            "Analytics (Plotly)",
        ]
    }
