# ◈ NeonStream Social Manager v1.2.0

Gestor de redes sociales de escritorio con estética **Retrowave/Outrun**, IA integrada (Google Gemini) y cifrado de tokens. Construido con Python + CustomTkinter.

## Plataformas soportadas

| Plataforma | Auth | Publicar | Analytics | Estado |
|-----------|------|---------|-----------|--------|
| LinkedIn   | OAuth2 | Texto, imágenes, links | Impresiones, clicks | ✅ PoC |
| X/Twitter  | OAuth2 PKCE | Tweets, media | Likes, retweets | ✅ Fase 2 |
| TikTok     | OAuth2 PKCE | Vídeo | — | ✅ Fase 3 |
| Telegram   | Bot Token | Texto, foto, vídeo, álbum | — | ✅ Fase 3 |
| Instagram  | OAuth2 Meta | Imagen, carrusel, Reels | Reach, impresiones | ✅ Fase 4 |
| Facebook   | OAuth2 Meta | — | — | 🔜 Fase 5 |

## Stack

| Capa | Tecnología |
|------|-----------|
| UI | CustomTkinter 5.x — paleta Outrun neón |
| Backend OAuth | FastAPI + uvicorn (daemon) |
| Base de datos | SQLite + SQLAlchemy 2.x |
| Cifrado tokens | Fernet AES-128 via `cryptography` |
| Scheduler | APScheduler 3.x (BackgroundScheduler) |
| IA | Google Gemini (google-genai SDK v2) |
| Gráficas | Plotly + kaleido / matplotlib fallback |
| Empaquetado | PyInstaller 6 + Inno Setup 6 |

## Inicio rápido (Windows)

```bat
:: 1. Extraer el ZIP en una carpeta
:: 2. Doble clic en setup.bat (crea .venv e instala deps)
:: 3. Abrir terminal en la carpeta
.venv\Scripts\python.exe desktop_main.py
```

## Configurar credenciales

Desde la app: **menú lateral → Credenciales ⚙**

O edita el `.env` directamente. Portales:
- LinkedIn: https://www.linkedin.com/developers/apps
- X/Twitter: https://developer.twitter.com/en/portal
- TikTok: https://developers.tiktok.com/
- Telegram: https://t.me/BotFather
- Instagram: https://developers.facebook.com/apps/
- Gemini: https://aistudio.google.com/app/apikey

## Tests

```bash
pytest                              # 105 tests
pytest tests/test_crypto_and_models.py   # seguridad
pytest tests/test_providers.py           # OAuth + scheduler + Gemini
pytest tests/test_new_providers.py       # TikTok, Telegram, Instagram, EnvManager
```

## Compilar .exe

```bat
build.bat           :: PyInstaller → dist/NeonStream/NeonStream.exe
build.bat --full    :: + Inno Setup → NeonStream_Setup_1.2.0.exe
```

## Seguridad

- Tokens OAuth2 cifrados con **Fernet** (AES-128-CBC + HMAC-SHA256)
- `FERNET_MASTER_KEY` generada automáticamente en primera ejecución
- State anti-CSRF con `hmac.compare_digest` (tiempo constante)
- Audit log inmutable para todas las operaciones sensibles
- `EnvManager` con whitelist — nunca expone `FERNET_MASTER_KEY` ni `APP_SECRET_KEY`
- Sin tokens en texto plano en ningún log, columna de BD ni UI

## Arquitectura

```
NeonStream/
├── desktop_main.py       ← punto de entrada (splash, deps check, boot)
├── config.py             ← Settings Pydantic + validación
├── models/database.py    ← ORM + EncryptedString TypeDecorator
├── providers/
│   ├── base.py           ← SocialMediaProvider ABC
│   ├── linkedin.py       ← OAuth2 + UGC Posts API v2
│   ├── x_twitter.py      ← OAuth2 PKCE + API v2
│   ├── tiktok.py         ← OAuth2 PKCE + Video Publish API v2
│   ├── telegram.py       ← Bot API (sin OAuth)
│   └── instagram.py      ← OAuth2 Meta + Graph API v19
├── services/
│   ├── crypto.py         ← Fernet singleton
│   ├── gemini_ai.py      ← Google Gemini (google-genai v2)
│   ├── scheduler.py      ← APScheduler + toast notifications
│   ├── oauth_bridge.py   ← servidor FastAPI daemon (callbacks OAuth)
│   ├── env_manager.py    ← lectura/escritura segura del .env
│   └── logging_config.py ← silenciar loggers externos
├── ui/
│   ├── theme.py          ← paleta Outrun + blend_hex
│   ├── app_window.py     ← ventana principal CTk + notify()
│   ├── components/
│   │   ├── sidebar.py    ← navegación lateral
│   │   ├── status_bar.py ← estado DB/scheduler/Gemini
│   │   └── toast.py      ← notificaciones flotantes
│   └── views/
│       ├── dashboard_view.py   ← stats + feed en vivo
│       ├── scheduler_view.py   ← CRUD posts + programación
│       ├── ai_lab_view.py      ← 4 tabs Gemini
│       ├── analytics_view.py   ← Plotly/matplotlib
│       ├── settings_view.py    ← cuentas OAuth
│       └── config_view.py      ← credenciales API + verificación
├── tests/                ← 105 tests unitarios
├── neonstream.spec       ← PyInstaller config
└── installer/neonstream.iss  ← Inno Setup
```
