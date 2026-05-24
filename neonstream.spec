# -*- mode: python ; coding: utf-8 -*-
# ══════════════════════════════════════════════════════════════════════════════
#  neonstream.spec — Configuración PyInstaller para NeonStream Social Manager
#
#  Genera un bundle onedir (carpeta) más rápido de arrancar que onefile.
#  El instalador Inno Setup lo empaqueta después en un .exe de instalación.
#
#  Uso:
#    pyinstaller neonstream.spec
#    → genera dist/NeonStream/
#
#  Notas importantes:
#    • CustomTkinter necesita incluir sus assets (themes, images) manualmente.
#    • kaleido (Plotly → PNG) necesita sus binarios nativos.
#    • APScheduler SQLAlchemy jobstore necesita el driver SQLite.
#    • uvicorn necesita su worker loop (asyncio).
#    • La DB y el .env se crean en tiempo de ejecución, NO van en el bundle.
# ══════════════════════════════════════════════════════════════════════════════

import os
import sys
from pathlib import Path
import customtkinter

block_cipher = None
PROJECT_ROOT = Path(SPECPATH)   # noqa: F821 — PyInstaller inyecta SPECPATH

# ── Buscar la carpeta de assets de CustomTkinter ─────────────────────────────
CTK_DIR = Path(customtkinter.__file__).parent


# ══════════════════════════════════════════════════════════════════════════════
#  Analysis — recopila todos los módulos y datos
# ══════════════════════════════════════════════════════════════════════════════

a = Analysis(
    # Punto de entrada
    [str(PROJECT_ROOT / "desktop_main.py")],

    pathex=[str(PROJECT_ROOT)],

    # DLLs adicionales (Windows) — dejar vacío, PyInstaller las detecta solo
    binaries=[],

    # ── Datos no-Python que deben incluirse en el bundle ─────────────────────
    datas=[
        # Assets de CustomTkinter (themes JSON, imágenes)
        (str(CTK_DIR / "assets"), "customtkinter/assets"),

        # Nuestros assets (icono, etc.)
        (str(PROJECT_ROOT / "ui" / "assets"), "ui/assets"),

        # .env.example para la primera ejecución
        (str(PROJECT_ROOT / ".env.example"), "."),
    ],

    # ── Imports ocultos (PyInstaller no los detecta automáticamente) ──────────
    hiddenimports=[
        # CustomTkinter widgets (algunos son importados dinámicamente)
        "customtkinter",
        "customtkinter.windows",
        "customtkinter.windows.widgets",
        "customtkinter.windows.widgets.theme",

        # Cryptography backends
        "cryptography.hazmat.primitives.ciphers.algorithms",
        "cryptography.hazmat.primitives.ciphers.modes",
        "cryptography.hazmat.backends.openssl",
        "cryptography.hazmat.backends.openssl.backend",

        # SQLAlchemy dialects
        "sqlalchemy.dialects.sqlite",
        "sqlalchemy.dialects.sqlite.pysqlite",

        # APScheduler jobstores y executors
        "apscheduler.jobstores.sqlalchemy",
        "apscheduler.executors.asyncio",
        "apscheduler.schedulers.asyncio",
        "apscheduler.triggers.date",
        "apscheduler.triggers.cron",
        "apscheduler.triggers.interval",

        # Uvicorn / FastAPI internos
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.asyncio",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.websockets",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "uvicorn.main",
        "anyio",
        "anyio._backends._asyncio",
        "starlette.routing",
        "fastapi",

        # Gemini / Google AI (nueva SDK google-genai)
        "google.genai",
        "google.genai.types",
        "google.auth",
        "google.auth.transport",
        "google.auth.transport.requests",
        "google.oauth2",

        # Providers nuevos
        "providers.x_twitter",
        "providers.tiktok",
        "providers.telegram",
        "providers.instagram",

        # Servicios nuevos
        "services.env_manager",
        "services.logging_config",

        # Vistas nuevas
        "ui.views.config_view",
        "ui.views.dashboard_view",
        "ui.components.toast",

        # httpx (para requests OAuth)
        "httpx",
        "httpx._transports.default",

        # Plotly / kaleido
        "plotly",
        "plotly.graph_objects",
        "kaleido",

        # PIL (Pillow)
        "PIL",
        "PIL._tkinter_finder",
        "PIL.Image",
        "PIL.ImageDraw",
        "PIL.ImageFilter",

        # Pydantic
        "pydantic",
        "pydantic_settings",
        "pydantic.v1",

        # Otros
        "dotenv",
        "python_dotenv",
        "packaging",
        "packaging.version",
        "pkg_resources",
        "pkg_resources._vendor",
    ],

    # ── Excluir módulos pesados que no usamos ─────────────────────────────────
    excludes=[
        "matplotlib",    # Usamos Plotly, no matplotlib
        "numpy",         # Solo necesario para pandas/plotly — incluir si falla
        "scipy",
        "IPython",
        "jupyter",
        "notebook",
        "tkinter.test",
        "unittest",
        "xmlrpc",
        "email.mime",
        "distutils",
        "setuptools",
        "pip",
        "wheel",
    ],

    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)


# ══════════════════════════════════════════════════════════════════════════════
#  PYZ — archivo de bytecodes comprimidos
# ══════════════════════════════════════════════════════════════════════════════

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)   # noqa: F821


# ══════════════════════════════════════════════════════════════════════════════
#  EXE — el ejecutable principal
# ══════════════════════════════════════════════════════════════════════════════

exe = EXE(   # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,          # onedir: los binarios van en COLLECT
    name="NeonStream",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,                       # Comprimir con UPX si está instalado
    upx_exclude=[
        # No comprimir DLLs que UPX puede romper
        "vcruntime140.dll",
        "python*.dll",
        "_tkinter*.pyd",
    ],
    console=False,                  # Sin ventana de consola en producción
                                    # Cambiar a True para debugging
    icon=str(PROJECT_ROOT / "ui" / "assets" / "neonstream.ico"),
    version_file=str(PROJECT_ROOT / "installer" / "version_info.txt")
    if (PROJECT_ROOT / "installer" / "version_info.txt").exists() else None,
)


# ══════════════════════════════════════════════════════════════════════════════
#  COLLECT — agrupa todo en dist/NeonStream/
# ══════════════════════════════════════════════════════════════════════════════

coll = COLLECT(   # noqa: F821
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=["vcruntime140.dll", "python*.dll", "_tkinter*.pyd"],
    name="NeonStream",
)
