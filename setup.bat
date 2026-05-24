@echo off
:: ══════════════════════════════════════════════════════════════════════════════
::  setup.bat — Configuración inicial de NeonStream en Windows
::  Uso: Doble clic o ejecutar desde terminal en la carpeta del proyecto
:: ══════════════════════════════════════════════════════════════════════════════
setlocal enabledelayedexpansion
chcp 65001 > nul 2>&1

set VENV=.venv

echo.
echo   [96m◈ NEONSTREAM Social Manager — Setup[0m
echo   ════════════════════════════════════
echo.

:: ── Verificar Python ──────────────────────────────────────────────────────────
echo   [1/4] Verificando Python 3.11+...
python --version > nul 2>&1
if errorlevel 1 (
    echo   [91m[ERROR][0m Python no encontrado.
    echo          Descargalo en https://www.python.org/downloads/
    echo          Asegurate de marcar "Add Python to PATH" al instalar.
    pause & exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PY_VER=%%v
echo   [92m[OK][0m    Python !PY_VER!

:: ── Entorno virtual ───────────────────────────────────────────────────────────
echo   [2/4] Creando entorno virtual...
if exist "%VENV%\Scripts\activate.bat" (
    echo   [92m[OK][0m    Entorno virtual ya existe.
) else (
    python -m venv %VENV%
    if errorlevel 1 (
        echo   [91m[ERROR][0m No se pudo crear el entorno virtual.
        pause & exit /b 1
    )
    echo   [92m[OK][0m    Entorno virtual creado en .venv\
)

:: ── Activar e instalar deps ───────────────────────────────────────────────────
echo   [3/4] Instalando dependencias (puede tardar 1-2 minutos)...
call %VENV%\Scripts\activate.bat
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo   [91m[ERROR][0m Fallo al instalar dependencias.
    echo          Revisa tu conexion a internet e intenta de nuevo.
    pause & exit /b 1
)
echo   [92m[OK][0m    Dependencias instaladas.

:: ── Generar .env si no existe ────────────────────────────────────────────────
echo   [4/4] Configurando entorno...
if not exist ".env" (
    python -c "
import secrets, os
from cryptography.fernet import Fernet
from pathlib import Path

env_example = Path('.env.example')
env_path = Path('.env')

fernet_key = Fernet.generate_key().decode()
app_secret = secrets.token_hex(32)

if env_example.exists():
    content = env_example.read_text(encoding='utf-8')
    content = content.replace('GENERA_CON_openssl_rand_hex_32', app_secret)
    content = content.replace('TU_CLAVE_FERNET_BASE64_AQUI', fernet_key)
    env_path.write_text(content, encoding='utf-8')
    print('  .env creado desde .env.example')
else:
    template = f'''APP_ENV=development
APP_SECRET_KEY={app_secret}
APP_HOST=127.0.0.1
APP_PORT=8000
APP_DEBUG=false
DATABASE_URL=sqlite:///./neonstream.db
FERNET_MASTER_KEY={fernet_key}
GEMINI_API_KEY=
GEMINI_MODEL=gemini-1.5-flash
LINKEDIN_CLIENT_ID=
LINKEDIN_CLIENT_SECRET=
LINKEDIN_REDIRECT_URI=http://127.0.0.1:8000/auth/linkedin/callback
LINKEDIN_SCOPES=openid,profile,email,w_member_social
X_CLIENT_ID=
X_CLIENT_SECRET=
X_REDIRECT_URI=http://127.0.0.1:8000/auth/x/callback
META_APP_ID=
META_APP_SECRET=
META_REDIRECT_URI=http://127.0.0.1:8000/auth/meta/callback
TIKTOK_CLIENT_KEY=
TIKTOK_CLIENT_SECRET=
TIKTOK_REDIRECT_URI=http://127.0.0.1:8000/auth/tiktok/callback
'''
    env_path.write_text(template, encoding='utf-8')
    print('  .env generado desde plantilla interna')
"
    echo   [92m[OK][0m    .env creado con claves generadas automaticamente.
    echo   [93m[AVISO][0m Edita .env para anadir tus API keys de LinkedIn, Gemini, etc.
) else (
    echo   [92m[OK][0m    .env ya existe.
)

:: ── Resumen ───────────────────────────────────────────────────────────────────
echo.
echo   ════════════════════════════════════
echo   [92m  Setup completado.[0m
echo.
echo   Para arrancar NeonStream:
echo   [96m    1. Activa el entorno:  .venv\Scripts\activate[0m
echo   [96m    2. Arranca la app:     py desktop_main.py[0m
echo.
echo   O directamente (sin activar el venv):
echo   [96m    .venv\Scripts\python.exe desktop_main.py[0m
echo   ════════════════════════════════════
echo.
pause
