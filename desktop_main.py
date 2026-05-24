"""
desktop_main.py — Punto de entrada de NeonStream (modo escritorio)
v1.0.2 — fixes Windows:
  • sys.path robusto: se añade ANTES de cualquier import de módulos locales
    y se fuerza incluso si ya estaba (puede estar como cwd relativo)
  • Checker de dependencias al arranque con mensaje accionable
  • Splash y bootstrap tolerantes a fallo de imports
"""
from __future__ import annotations

import logging
import multiprocessing
import os
import sys
from pathlib import Path


# ══════════════════════════════════════════════════════════════════════════════
#  PASO 0 — Rutas absolutas + sys.path  (PRIMERA instrucción del módulo)
# ══════════════════════════════════════════════════════════════════════════════

if getattr(sys, "frozen", False):
    # Ejecutable PyInstaller
    _BASE_DIR = Path(sys._MEIPASS).resolve()           # type: ignore[attr-defined]
    _DATA_DIR = Path(sys.executable).resolve().parent
else:
    # Desarrollo: __file__ puede ser relativo en Windows → .resolve() lo fija
    _BASE_DIR = Path(__file__).resolve().parent
    _DATA_DIR = _BASE_DIR

# Insertar al principio Y quitar duplicados/relativos para el mismo path
_base_str = str(_BASE_DIR)
# Limpiar entradas relativas al mismo directorio que puedan colisionar
sys.path = [p for p in sys.path if Path(p).resolve() != _BASE_DIR]
sys.path.insert(0, _base_str)

# CWD: necesario para sqlite:///./neonstream.db
try:
    if Path.cwd().resolve() != _DATA_DIR:
        os.chdir(_DATA_DIR)
except Exception:
    pass  # En algunos entornos frozen no se puede cambiar el CWD


# ══════════════════════════════════════════════════════════════════════════════
#  PASO 1 — Logging básico (sin deps externas)
# ══════════════════════════════════════════════════════════════════════════════

# Logging centralizado — silencia externos, configura Rich si disponible
from services.logging_config import configure_logging
configure_logging()
logger = logging.getLogger("neonstream")

# ── Aviso de versión de Python ────────────────────────────────────────────────
_PY = sys.version_info
if _PY < (3, 11):
    print(
        f"[ERROR] Python {_PY.major}.{_PY.minor} no soportado. "
        "NeonStream requiere Python 3.11 o superior.",
        file=sys.stderr,
    )
    sys.exit(1)
if _PY >= (3, 14):
    logger.warning(
        "Python %d.%d detectado. NeonStream se probó con 3.11–3.13. "
        "Si encuentras errores instala las últimas versiones de las deps: "
        "pip install -r requirements.txt --upgrade",
        _PY.major, _PY.minor,
    )

logger.info("Python %d.%d.%d", _PY.major, _PY.minor, _PY.micro)
logger.info("BASE_DIR = %s", _BASE_DIR)
logger.info("DATA_DIR = %s", _DATA_DIR)
logger.info("CWD      = %s", Path.cwd())
logger.info("sys.path[0] = %s", sys.path[0])


# ══════════════════════════════════════════════════════════════════════════════
#  PASO 2 — Verificar dependencias críticas ANTES de importar nada local
# ══════════════════════════════════════════════════════════════════════════════

# Mapa: nombre de import → nombre pip para instalar
# Las versiones son mínimas, no pinadas, para máxima compatibilidad.
_REQUIRED = {
    "customtkinter":    "customtkinter>=5.2.2",
    "sqlalchemy":       "sqlalchemy>=2.0.36",   # >=2.0.36 requerido para Python 3.13/3.14
    "cryptography":     "cryptography>=43.0.0",
    "dotenv":           "python-dotenv>=1.0.1",
    "fastapi":          "fastapi>=0.115.0",
    "uvicorn":          "uvicorn[standard]>=0.32.0",
    "apscheduler":      "apscheduler>=3.11.0",
    "httpx":            "httpx>=0.28.0",
    "pydantic":         "pydantic>=2.9.0",
    "pydantic_settings":"pydantic-settings>=2.5.0",
    "PIL":              "pillow>=10.3.0",
}


def _check_deps() -> list[str]:
    """
    Detecta paquetes faltantes o con versión incompatible.
    Captura cualquier Exception (no solo ImportError) porque paquetes
    instalados en versiones incompatibles de Python pueden lanzar
    TypeError, AttributeError, etc. al importarse (ej: SQLAlchemy <2.0.36
    en Python 3.14 lanza TypeError por __firstlineno__).
    """
    missing = []
    for import_name, pip_spec in _REQUIRED.items():
        try:
            mod = __import__(import_name)
            # Verificación especial: SQLAlchemy <2.0.36 falla en Python 3.13+
            if import_name == "sqlalchemy":
                from importlib.metadata import version as pkg_version
                sa_ver = tuple(int(x) for x in pkg_version("sqlalchemy").split(".")[:3])
                if sa_ver < (2, 0, 36):
                    missing.append(pip_spec)
        except Exception:
            # ImportError, TypeError, AttributeError… cualquier fallo al importar
            missing.append(pip_spec)
    return missing


def _check_project_structure() -> list[str]:
    """
    Verifica que los directorios y archivos locales del proyecto existen
    en _BASE_DIR. Si faltan, el usuario tiene una instalación incompleta
    (ej: solo descargó desktop_main.py sin el resto del proyecto).
    """
    required = [
        ("models",    "Carpeta"),
        ("ui",        "Carpeta"),
        ("services",  "Carpeta"),
        ("providers", "Carpeta"),
        ("config.py", "Archivo"),
    ]
    missing = []
    for name, kind in required:
        path = _BASE_DIR / name
        if not path.exists():
            missing.append(f"  {kind} faltante: {path}")
    return missing



def _show_incomplete_install(missing_paths: list[str]) -> None:
    """Muestra error cuando faltan carpetas/archivos del proyecto."""
    sep = chr(10)
    listing = sep.join(missing_paths)
    try:
        present = sorted(p.name for p in _BASE_DIR.iterdir())
        present_str = ("  " + (sep + "  ").join(present[:20]))
    except Exception:
        present_str = "  (no se pudo listar)"

    msg = (
        "La instalacion de NeonStream esta incompleta." + sep + sep
        + "Faltan los siguientes elementos en:" + sep + str(_BASE_DIR) + sep + sep
        + listing + sep + sep
        + "Contenido actual de la carpeta:" + sep + present_str + sep + sep
        + "Solucion: extrae el ZIP completo del proyecto en esta carpeta." + sep
        + "Debe contener: models/, ui/, services/, providers/, config.py"
    )
    logger.error("Instalacion incompleta: %s", listing.replace(sep, " | "))
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("NeonStream - Instalacion incompleta", msg)
        root.destroy()
    except Exception:
        print("INSTALACION INCOMPLETA" + sep + msg, file=__import__("sys").stderr)

def _show_missing_deps(missing: list[str]) -> None:
    """Muestra un diálogo con las instrucciones de instalación."""
    pip_line = " ".join(missing)
    msg = (
        "Faltan dependencias de Python necesarias para arrancar NeonStream.\n\n"
        "Ejecuta este comando en la terminal (con el entorno virtual activo):\n\n"
        f"    pip install {pip_line}\n\n"
        "O instala todas las dependencias con:\n\n"
        "    pip install -r requirements.txt\n\n"
        f"Directorio del proyecto: {_BASE_DIR}"
    )
    logger.error("Dependencias faltantes: %s", ", ".join(missing))
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("NeonStream — Dependencias faltantes", msg)
        root.destroy()
    except Exception:
        print(f"\n{'='*60}\nDEPENDENCIAS FALTANTES\n{'='*60}\n{msg}\n", file=sys.stderr)


# ══════════════════════════════════════════════════════════════════════════════
#  PASO 3 — Gestión del .env
# ══════════════════════════════════════════════════════════════════════════════

_ENV_TEMPLATE = """\
# NeonStream Social Manager — configuración generada automáticamente
APP_ENV=development
APP_SECRET_KEY={app_secret}
APP_HOST=127.0.0.1
APP_PORT=8000
APP_DEBUG=false
DATABASE_URL=sqlite:///./neonstream.db

# IMPORTANTE: no compartas esta clave. Sin ella los tokens son irrecuperables.
FERNET_MASTER_KEY={fernet_key}

# ── Google Gemini ─────────────────────────────────────────────────────────────
# Obtén tu clave en https://aistudio.google.com/app/apikey
GEMINI_API_KEY=
GEMINI_MODEL=gemini-1.5-flash

# ── LinkedIn (Portal: https://www.linkedin.com/developers/apps) ───────────────
LINKEDIN_CLIENT_ID=
LINKEDIN_CLIENT_SECRET=
LINKEDIN_REDIRECT_URI=http://127.0.0.1:8000/auth/linkedin/callback
LINKEDIN_SCOPES=openid,profile,email,w_member_social

# ── X / Twitter (Portal: https://developer.twitter.com/en/portal) ────────────
X_CLIENT_ID=
X_CLIENT_SECRET=
X_REDIRECT_URI=http://127.0.0.1:8000/auth/x/callback

# ── Meta / Instagram (Portal: https://developers.facebook.com) ───────────────
META_APP_ID=
META_APP_SECRET=
META_REDIRECT_URI=http://127.0.0.1:8000/auth/meta/callback

# ── TikTok (Portal: https://developers.tiktok.com) ───────────────────────────
TIKTOK_CLIENT_KEY=
TIKTOK_CLIENT_SECRET=
TIKTOK_REDIRECT_URI=http://127.0.0.1:8000/auth/tiktok/callback
"""


def _inject_fernet_key(env_path: Path, new_key: str) -> None:
    import re
    content = env_path.read_text(encoding="utf-8")
    if re.search(r"^FERNET_MASTER_KEY\s*=", content, re.MULTILINE):
        content = re.sub(
            r"^(FERNET_MASTER_KEY\s*=).*$",
            rf"\g<1>{new_key}",
            content, flags=re.MULTILINE,
        )
    else:
        content += f"\nFERNET_MASTER_KEY={new_key}\n"
    env_path.write_text(content, encoding="utf-8")


def _ensure_env() -> bool:
    import secrets
    from cryptography.fernet import Fernet
    from dotenv import load_dotenv

    env_path = _DATA_DIR / ".env"

    # 1. Ya existe → cargar y verificar
    if env_path.exists():
        load_dotenv(env_path, override=False)
        key = os.getenv("FERNET_MASTER_KEY", "").strip()
        if key and key not in ("TU_CLAVE_FERNET_BASE64_AQUI", ""):
            logger.info(".env válido encontrado: %s", env_path)
            return True
        logger.warning(".env sin FERNET_MASTER_KEY válida — inyectando clave nueva…")
        _inject_fernet_key(env_path, Fernet.generate_key().decode())
        load_dotenv(env_path, override=True)
        return True

    # Claves nuevas
    new_fernet = Fernet.generate_key().decode()
    new_secret  = secrets.token_hex(32)

    # 2. Existe .env.example
    candidates = [
        _DATA_DIR / ".env.example",
        _BASE_DIR / ".env.example",
    ]
    example = next((p for p in candidates if p.exists()), None)

    if example:
        import shutil
        shutil.copy(example, env_path)
        content = env_path.read_text(encoding="utf-8")
        content = content.replace("GENERA_CON_openssl_rand_hex_32", new_secret)
        content = content.replace("TU_CLAVE_FERNET_BASE64_AQUI",    new_fernet)
        env_path.write_text(content, encoding="utf-8")
        logger.info(".env creado desde .env.example")
    else:
        # 3. Generar desde plantilla interna
        logger.info(".env.example no encontrado — generando desde plantilla interna")
        env_path.write_text(
            _ENV_TEMPLATE.format(app_secret=new_secret, fernet_key=new_fernet),
            encoding="utf-8",
        )
        logger.info(".env generado en: %s", env_path)

    load_dotenv(env_path, override=True)
    return True


# ══════════════════════════════════════════════════════════════════════════════
#  PASO 4 — Splash screen
# ══════════════════════════════════════════════════════════════════════════════

def _show_splash():
    try:
        import customtkinter as ctk
        from ui.theme import COLORS, FONTS, apply_theme
        apply_theme()

        splash = ctk.CTk()
        splash.title("")
        splash.geometry("420x220")
        splash.resizable(False, False)
        splash.configure(fg_color=COLORS["bg_deep"])
        splash.overrideredirect(True)

        splash.update_idletasks()
        x = (splash.winfo_screenwidth()  - 420) // 2
        y = (splash.winfo_screenheight() - 220) // 2
        splash.geometry(f"420x220+{x}+{y}")

        ctk.CTkLabel(
            splash, text="◈ NEONSTREAM",
            font=("Consolas", 28, "bold"),
            text_color=COLORS["neon_purple"],
        ).place(relx=0.5, rely=0.28, anchor="center")

        ctk.CTkLabel(
            splash, text="Social Manager",
            font=("Consolas", 13),
            text_color=COLORS["neon_cyan"],
        ).place(relx=0.5, rely=0.48, anchor="center")

        progress = ctk.CTkProgressBar(
            splash, width=300, height=4,
            progress_color=COLORS["neon_purple"],
            fg_color=COLORS["border"],
            corner_radius=2,
        )
        progress.place(relx=0.5, rely=0.68, anchor="center")
        progress.set(0)

        status_lbl = ctk.CTkLabel(
            splash, text="Iniciando servicios…",
            font=FONTS["small"],
            text_color=COLORS["text_disabled"],
        )
        status_lbl.place(relx=0.5, rely=0.84, anchor="center")

        splash.update()

        def _animate(val: float = 0.0):
            if val <= 1.0:
                progress.set(val)
                splash.after(30, lambda: _animate(round(val + 0.04, 2)))

        splash.after(50, _animate)
        splash.update()
        return splash, status_lbl

    except Exception as exc:
        logger.warning("Splash no disponible: %s", exc)
        return None, None


def _update_splash(label, text: str) -> None:
    if label is None:
        return
    try:
        label.configure(text=text)
        label.winfo_toplevel().update()
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
#  PASO 5 — Bootstrap
# ══════════════════════════════════════════════════════════════════════════════

def _bootstrap(on_step=None) -> None:
    step = on_step or (lambda _: None)

    step("Inicializando base de datos…")
    from models.database import init_db
    init_db()
    logger.info("Base de datos lista.")

    step("Validando configuración…")
    from config import get_settings
    s = get_settings()
    logger.info("Config OK: env=%s db=%s", s.app_env, s.database_url)

    step("Listo.")


# ══════════════════════════════════════════════════════════════════════════════
#  PASO 6 — Error fatal con diálogo nativo
# ══════════════════════════════════════════════════════════════════════════════

def _fatal(title: str, message: str) -> None:
    logger.error("FATAL — %s: %s", title, message)
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(f"NeonStream — {title}", message)
        root.destroy()
    except Exception:
        print(f"\nFATAL: {title}\n{message}\n", file=sys.stderr)


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    multiprocessing.freeze_support()

    # ── 1. Verificar estructura local del proyecto ───────────────────────────
    missing_paths = _check_project_structure()
    if missing_paths:
        _show_incomplete_install(missing_paths)
        sys.exit(1)

    # ── 2. Verificar dependencias Python ─────────────────────────────────────
    missing = _check_deps()
    if missing:
        _show_missing_deps(missing)
        sys.exit(1)

    # ── 2. Entorno ────────────────────────────────────────────────────────────
    if not _ensure_env():
        _fatal(
            "Configuración incompleta",
            f"No se pudo crear el archivo .env en:\n{_DATA_DIR}\n\n"
            "Verifica que tienes permisos de escritura.",
        )
        return

    # ── 3. Splash ─────────────────────────────────────────────────────────────
    splash, status_lbl = _show_splash()

    # ── 4. Bootstrap en hilo daemon ───────────────────────────────────────────
    import threading
    boot_done  = threading.Event()
    boot_error: list[str] = []

    def _do_boot() -> None:
        try:
            _bootstrap(on_step=lambda msg: _update_splash(status_lbl, msg))
        except Exception as exc:
            boot_error.append(str(exc))
            logger.exception("Error en bootstrap: %s", exc)
        finally:
            boot_done.set()

    threading.Thread(target=_do_boot, name="neonstream-boot", daemon=True).start()

    # Mantener splash vivo (máx 15 s)
    import time
    deadline = time.monotonic() + 15.0
    while not boot_done.is_set() and time.monotonic() < deadline:
        if splash:
            try:
                splash.update()
            except Exception:
                break
        time.sleep(0.04)

    if not boot_done.is_set():
        logger.warning("Bootstrap tardó más de 15 s — continuando igualmente.")

    # ── 5. Cerrar splash ──────────────────────────────────────────────────────
    if splash:
        try:
            splash.destroy()
        except Exception:
            pass

    if boot_error:
        _fatal("Error de inicio", boot_error[0])
        return

    # ── 6. Ventana principal ──────────────────────────────────────────────────
    logger.info("Arrancando NeonStream UI…")
    try:
        from ui.app_window import AppWindow
        app = AppWindow()
        app.mainloop()
    except Exception as exc:
        logger.exception("Error crítico en la UI: %s", exc)
        _fatal("Error de interfaz", str(exc))

    logger.info("NeonStream cerrado correctamente.")


if __name__ == "__main__":
    main()
