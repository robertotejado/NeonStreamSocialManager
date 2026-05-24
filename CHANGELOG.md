# NeonStream Social Manager — Changelog

## v1.2.0 (actual)
### Nuevas características
- **Instagram provider** — Meta Graph API v19, Container Model, carrusel, Reels
- **Toast notifications** — alertas flotantes Retrowave al publicar/fallar
- **Config view: verificación en tiempo real** — botón Verificar para Gemini y Telegram Bot Token
- **PyInstaller .spec actualizado** — todos los providers y servicios nuevos incluidos

## v1.1.0
### Nuevas características
- **TikTok provider** — OAuth2 PKCE, Video Publish API v2 (chunked upload)
- **Telegram provider** — Bot API, sendMessage/sendPhoto/sendVideo/sendMediaGroup
- **Pantalla Credenciales** — editar API keys desde la UI sin tocar el .env
- **EnvManager** — lectura/escritura segura del .env con whitelist de claves
- **Dashboard en vivo** — stats en tiempo real + feed de actividad + auto-refresh 30s
- **TELEGRAM/TIKTOK** añadidos al enum SocialPlatform y al scheduler

### Fixes
- `blend_hex()` — colores alpha válidos para tkinter (sustituye `#rrggbbaa`)
- `BackgroundScheduler` — sustituye AsyncIOScheduler (incompatible con tkinter)
- `kaleido.write_fig` async — envuelto con `asyncio.run()` correctamente

## v1.0.7
### Nuevas características
- **X/Twitter provider** — OAuth2 PKCE, tweets, media upload chunked, métricas
- **X registrado** en OAuthBridge, scheduler y settings UI

### Fixes
- `kaleido.write_fig` coroutine warning
- X `no implementado aún` en start_oauth_flow

## v1.0.6
### Fixes
- `blend_hex` no importado en settings_view → NameError
- `lambda exc` scope en analytics_view → Python 3.12+ variable destruida en except
- Kaleido 1.3.0 incompatible con Plotly 5.x → fallback matplotlib

## v1.0.5
### Nuevas características
- **Dashboard real** con stats, feed de actividad, panel de cuentas
- **logging_config.py** — silencia 15+ loggers externos (kaleido, SQLAlchemy…)

### Fixes
- `corner_radius` duplicado en CTkButton — auditoría completa
- `"transparent"` inválido en CTkScrollableFrame
- APScheduler `no running event loop` → BackgroundScheduler

## v1.0.4
### Fixes
- `corner_radius` fix en todas las vistas (Settings, AI Lab, Scheduler)
- `"transparent"` en CTkScrollableFrame → color real
- APScheduler: BackgroundScheduler para escritorio

## v1.0.3 — v1.0.1
### Fixes progresivos
- `No module named 'models'` — sys.path absoluto
- `No module named 'customtkinter'` — checker de deps con diálogo
- `FERNET_MASTER_KEY` no encontrada — generación automática inline
- `.env.example` opcional — plantilla interna como fallback
- SQLAlchemy `__firstlineno__` en Python 3.14 → `>=2.0.36` requerido

## v1.0.0 — PoC inicial
- LinkedIn OAuth2 completo (Fase 1)
- Cifrado Fernet de tokens en BD
- APScheduler con jobstore SQLite
- Gemini AI (google-genai SDK v2)
- Estructura modular de providers (ABC SocialMediaProvider)
- 63 tests unitarios
