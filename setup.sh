#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
#  NeonStream Social Manager — Script de configuración inicial
#  Uso: bash setup.sh
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

VENV_DIR=".venv"
PYTHON_MIN="3.11"

# ── Colores Retrowave para la terminal ────────────────────────────────────────
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

banner() {
  echo -e "${MAGENTA}"
  echo "  ███╗   ██╗███████╗ ██████╗ ███╗   ██╗███████╗████████╗██████╗ ███████╗ █████╗ ███╗   ███╗"
  echo "  ████╗  ██║██╔════╝██╔═══██╗████╗  ██║██╔════╝╚══██╔══╝██╔══██╗██╔════╝██╔══██╗████╗ ████║"
  echo "  ██╔██╗ ██║█████╗  ██║   ██║██╔██╗ ██║███████╗   ██║   ██████╔╝█████╗  ███████║██╔████╔██║"
  echo "  ██║╚██╗██║██╔══╝  ██║   ██║██║╚██╗██║╚════██║   ██║   ██╔══██╗██╔══╝  ██╔══██║██║╚██╔╝██║"
  echo "  ██║ ╚████║███████╗╚██████╔╝██║ ╚████║███████║   ██║   ██║  ██║███████╗██║  ██║██║ ╚═╝ ██║"
  echo "  ╚═╝  ╚═══╝╚══════╝ ╚═════╝ ╚═╝  ╚═══╝╚══════╝   ╚═╝   ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═╝     ╚═╝"
  echo -e "${CYAN}  Social Manager — Setup v1.0${NC}"
  echo ""
}

info()    { echo -e "${CYAN}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC}   $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# ── 1. Verificar versión de Python ────────────────────────────────────────────
check_python() {
  info "Verificando Python >= ${PYTHON_MIN}..."
  if ! command -v python3 &>/dev/null; then
    error "Python3 no encontrado. Instala Python ${PYTHON_MIN}+ antes de continuar."
  fi
  PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
  if python3 -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)"; then
    success "Python ${PY_VER} detectado."
  else
    error "Python ${PY_VER} no es suficiente. Necesitas >= ${PYTHON_MIN}."
  fi
}

# ── 2. Crear entorno virtual ──────────────────────────────────────────────────
create_venv() {
  if [ -d "${VENV_DIR}" ]; then
    info "Entorno virtual '${VENV_DIR}' ya existe. Omitiendo creación."
  else
    info "Creando entorno virtual en '${VENV_DIR}'..."
    python3 -m venv "${VENV_DIR}"
    success "Entorno virtual creado."
  fi
}

# ── 3. Instalar dependencias ──────────────────────────────────────────────────
install_deps() {
  info "Instalando dependencias desde requirements.txt..."
  "${VENV_DIR}/bin/pip" install --upgrade pip --quiet
  "${VENV_DIR}/bin/pip" install -r requirements.txt --quiet
  success "Dependencias instaladas."
}

# ── 4. Generar .env a partir de .env.example ─────────────────────────────────
setup_env() {
  if [ -f ".env" ]; then
    info ".env ya existe. No se sobreescribe."
  else
    info "Creando .env desde .env.example..."
    cp .env.example .env

    # Generar APP_SECRET_KEY automáticamente
    SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    sed -i "s/GENERA_CON_openssl_rand_hex_32/${SECRET}/" .env

    # Generar FERNET_MASTER_KEY automáticamente
    FERNET=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
    sed -i "s|TU_CLAVE_FERNET_BASE64_AQUI|${FERNET}|" .env

    success ".env creado con claves generadas automáticamente."
    echo -e "${RED}  ⚠️  GUARDA LA FERNET_MASTER_KEY EN UN LUGAR SEGURO. Sin ella, los tokens son irrecuperables.${NC}"
  fi
}

# ── 5. Inicializar base de datos ──────────────────────────────────────────────
init_db() {
  info "Inicializando base de datos SQLite..."
  "${VENV_DIR}/bin/python" -c "
from dotenv import load_dotenv
load_dotenv()
from models.database import init_db
init_db()
print('Base de datos inicializada.')
"
  success "Base de datos lista."
}

# ── Main ──────────────────────────────────────────────────────────────────────
banner
check_python
create_venv
install_deps
setup_env
init_db

echo ""
echo -e "${MAGENTA}══════════════════════════════════════════════${NC}"
echo -e "${GREEN}  NeonStream listo para arrancar.${NC}"
echo -e "${CYAN}  Activa el entorno:  source ${VENV_DIR}/bin/activate${NC}"
echo -e "${CYAN}  Arranca el server:  uvicorn main:app --reload${NC}"
echo -e "${MAGENTA}══════════════════════════════════════════════${NC}"
