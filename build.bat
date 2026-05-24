@echo off
:: ══════════════════════════════════════════════════════════════════════════════
::  build.bat — Compilación one-click de NeonStream para Windows
::
::  Pasos:
::    1. Verificar entorno virtual
::    2. Instalar/actualizar dependencias
::    3. Generar icono .ico
::    4. Limpiar builds anteriores
::    5. PyInstaller → dist/NeonStream/
::    6. Inno Setup  → installer/output/NeonStream_Setup_x.x.x.exe  (opcional)
::
::  Uso:
::    build.bat           → solo PyInstaller
::    build.bat --full    → PyInstaller + Inno Setup
::    build.bat --clean   → limpia y sale
:: ══════════════════════════════════════════════════════════════════════════════
setlocal enabledelayedexpansion

set APP_NAME=NeonStream
set VERSION=1.0.0
set VENV=.venv
set SPEC=neonstream.spec
set DIST_DIR=dist\%APP_NAME%
set BUILD_DIR=build
set INNO_COMPILER="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
set ISS_SCRIPT=installer\neonstream.iss

:: Colores en terminal (requiere Windows 10+)
set RED=[91m
set GREEN=[92m
set CYAN=[96m
set MAGENTA=[95m
set YELLOW=[93m
set RESET=[0m

:: ── Banner ────────────────────────────────────────────────────────────────────
echo %MAGENTA%
echo   ================================
echo    NEONSTREAM  Build System v%VERSION%
echo   ================================
echo %RESET%

:: ── Argumento --clean ─────────────────────────────────────────────────────────
if "%1"=="--clean" (
    echo %YELLOW%[CLEAN]%RESET% Limpiando builds anteriores...
    if exist "%DIST_DIR%" rmdir /s /q "%DIST_DIR%"
    if exist "%BUILD_DIR%" rmdir /s /q "%BUILD_DIR%"
    if exist "*.spec.bak" del /q "*.spec.bak"
    echo %GREEN%[OK]%RESET% Limpieza completada.
    goto :EOF
)

:: ── Verificar Python ──────────────────────────────────────────────────────────
echo %CYAN%[1/6]%RESET% Verificando Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo %RED%[ERROR]%RESET% Python no encontrado. Instala Python 3.11+.
    pause & exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PY_VER=%%v
echo %GREEN%[OK]%RESET% Python %PY_VER%

:: ── Activar entorno virtual ───────────────────────────────────────────────────
echo %CYAN%[2/6]%RESET% Activando entorno virtual...
if not exist "%VENV%\Scripts\activate.bat" (
    echo %YELLOW%[WARN]%RESET% Entorno virtual no encontrado. Creando...
    python -m venv %VENV%
    if errorlevel 1 (
        echo %RED%[ERROR]%RESET% No se pudo crear el entorno virtual.
        pause & exit /b 1
    )
)
call %VENV%\Scripts\activate.bat
echo %GREEN%[OK]%RESET% Entorno virtual activo.

:: ── Instalar dependencias ─────────────────────────────────────────────────────
echo %CYAN%[3/6]%RESET% Instalando dependencias...
pip install -r requirements.txt --quiet --upgrade
if errorlevel 1 (
    echo %RED%[ERROR]%RESET% Falló la instalación de dependencias.
    pause & exit /b 1
)
:: Asegurar pyinstaller y kaleido explícitamente
pip install pyinstaller kaleido --quiet --upgrade
echo %GREEN%[OK]%RESET% Dependencias instaladas.

:: ── Generar icono ─────────────────────────────────────────────────────────────
echo %CYAN%[4/6]%RESET% Generando icono...
if not exist "ui\assets\neonstream.ico" (
    python ui\assets\generate_icon.py
    if errorlevel 1 (
        echo %YELLOW%[WARN]%RESET% No se pudo generar el icono. Continuando sin icono personalizado.
    ) else (
        echo %GREEN%[OK]%RESET% Icono generado: ui\assets\neonstream.ico
    )
) else (
    echo %GREEN%[OK]%RESET% Icono ya existe: ui\assets\neonstream.ico
)

:: ── Limpiar dist anterior ─────────────────────────────────────────────────────
echo %CYAN%[5/6]%RESET% Limpiando builds anteriores...
if exist "%DIST_DIR%" rmdir /s /q "%DIST_DIR%"
if exist "%BUILD_DIR%\%APP_NAME%" rmdir /s /q "%BUILD_DIR%\%APP_NAME%"
echo %GREEN%[OK]%RESET% Limpieza completada.

:: ── PyInstaller ───────────────────────────────────────────────────────────────
echo %CYAN%[6/6]%RESET% Compilando con PyInstaller...
echo.
pyinstaller %SPEC% --noconfirm --log-level WARN
if errorlevel 1 (
    echo.
    echo %RED%[ERROR]%RESET% PyInstaller falló. Revisa los mensajes anteriores.
    pause & exit /b 1
)

echo.
echo %GREEN%[OK]%RESET% Bundle generado en: %DIST_DIR%\

:: ── Mostrar tamaño del bundle ─────────────────────────────────────────────────
for /f "tokens=3" %%s in ('dir /s /-c "%DIST_DIR%" ^| find "bytes"') do set BUNDLE_SIZE=%%s
echo %CYAN%[INFO]%RESET% Tamaño del bundle: %BUNDLE_SIZE% bytes

:: ── Inno Setup (opcional) ─────────────────────────────────────────────────────
if "%1"=="--full" (
    echo.
    echo %CYAN%[+]%RESET% Generando instalador con Inno Setup...
    if exist %INNO_COMPILER% (
        %INNO_COMPILER% %ISS_SCRIPT%
        if errorlevel 1 (
            echo %RED%[ERROR]%RESET% Inno Setup falló.
            pause & exit /b 1
        )
        echo %GREEN%[OK]%RESET% Instalador generado: installer\output\%APP_NAME%_Setup_%VERSION%.exe
    ) else (
        echo %YELLOW%[WARN]%RESET% Inno Setup no encontrado en %INNO_COMPILER%
        echo %YELLOW%[WARN]%RESET% Instálalo desde https://jrsoftware.org/isdl.php
    )
)

:: ── Resumen ───────────────────────────────────────────────────────────────────
echo.
echo %MAGENTA%══════════════════════════════════════%RESET%
echo %GREEN%  Build completado exitosamente.%RESET%
echo %CYAN%  Ejecutable: %DIST_DIR%\%APP_NAME%.exe%RESET%
if "%1"=="--full" (
    echo %CYAN%  Instalador: installer\output\%APP_NAME%_Setup_%VERSION%.exe%RESET%
)
echo %MAGENTA%══════════════════════════════════════%RESET%
echo.
pause
