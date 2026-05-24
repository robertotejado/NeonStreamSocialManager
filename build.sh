#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
#  build.sh — Compilación one-click de NeonStream para Linux/macOS
#
#  En Linux/Mac genera un bundle ejecutable (onedir).
#  Para generar el .exe de Windows desde Linux necesitas Wine + PyInstaller.
#
#  Uso:
#    bash build.sh           → bundle para el SO actual
#    bash build.sh --clean   → limpia y sale
#    bash build.sh --check   → solo verifica dependencias
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

APP_NAME="NeonStream"
VERSION="1.0.0"
VENV=".venv"
SPEC="neonstream.spec"
DIST_DIR="dist/${APP_NAME}"

# Colores
RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'
MAGENTA='\033[0;35m'; YELLOW='\033[0;33m'; NC='\033[0m'

step()  { echo -e "${CYAN}[$(printf '%d' $1)/6]${NC} $2"; }
ok()    { echo -e "${GREEN}[OK]${NC}   $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

echo -e "${MAGENTA}"
echo "  ================================"
echo "   NEONSTREAM  Build System v${VERSION}"
echo "  ================================"
echo -e "${NC}"

# ── Argumento --clean ─────────────────────────────────────────────────────────
if [[ "${1:-}" == "--clean" ]]; then
    echo -e "${YELLOW}[CLEAN]${NC} Limpiando builds anteriores..."
    rm -rf "${DIST_DIR}" "build/${APP_NAME}"
    ok "Limpieza completada."
    exit 0
fi

# ── 1. Verificar Python ───────────────────────────────────────────────────────
step 1 "Verificando Python 3.11+..."
if ! python3 -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" 2>/dev/null; then
    error "Python 3.11+ requerido. Versión actual: $(python3 --version 2>&1)"
fi
ok "$(python3 --version)"

# ── 2. Entorno virtual ────────────────────────────────────────────────────────
step 2 "Preparando entorno virtual..."
if [[ ! -d "${VENV}" ]]; then
    python3 -m venv "${VENV}"
    ok "Entorno virtual creado."
fi
# shellcheck disable=SC1090
source "${VENV}/bin/activate"
ok "Entorno virtual activo: ${VENV}"

# ── 3. Dependencias ───────────────────────────────────────────────────────────
step 3 "Instalando dependencias..."
pip install -r requirements.txt --quiet --upgrade
pip install pyinstaller kaleido --quiet --upgrade
ok "Dependencias instaladas."

# ── 4. Icono ──────────────────────────────────────────────────────────────────
step 4 "Generando icono..."
if [[ ! -f "ui/assets/neonstream.ico" ]]; then
    if python3 ui/assets/generate_icon.py; then
        ok "Icono generado: ui/assets/neonstream.ico"
    else
        warn "No se pudo generar el icono. Continuando sin él."
    fi
else
    ok "Icono ya existe."
fi

# ── 5. Limpiar dist anterior ──────────────────────────────────────────────────
step 5 "Limpiando builds anteriores..."
rm -rf "${DIST_DIR}" "build/${APP_NAME}"
ok "Limpieza completada."

# ── 6. PyInstaller ────────────────────────────────────────────────────────────
step 6 "Compilando con PyInstaller..."
echo ""
pyinstaller "${SPEC}" --noconfirm --log-level WARN

echo ""
ok "Bundle generado en: ${DIST_DIR}/"

# Tamaño
BUNDLE_SIZE=$(du -sh "${DIST_DIR}" 2>/dev/null | cut -f1 || echo "?")
echo -e "${CYAN}[INFO]${NC} Tamaño del bundle: ${BUNDLE_SIZE}"

# ── Resumen ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${MAGENTA}══════════════════════════════════════${NC}"
echo -e "${GREEN}  Build completado exitosamente.${NC}"
echo -e "${CYAN}  Ejecutable: ${DIST_DIR}/${APP_NAME}${NC}"
echo -e "${MAGENTA}══════════════════════════════════════${NC}"
