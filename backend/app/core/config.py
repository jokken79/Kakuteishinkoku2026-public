"""Configuracion de la aplicacion via Pydantic Settings.

Carga variables de entorno (con prefijo opcional) desde el entorno del proceso
o desde un archivo `.env`. Estos valores son la unica fuente de configuracion
del backend (nunca hardcodear secrets ni URLs en codigo).
"""

from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings de la aplicacion.

    Args:
        app_name: Nombre legible del servicio.
        app_version: Version del servicio.
        api_prefix: Prefijo comun de todas las rutas de la API.
        database_url: URL de conexion a PostgreSQL (SQLAlchemy/psycopg2).
        cors_origins: Lista de origenes permitidos para CORS.
        frontend_dist: Carpeta del build de la PWA a servir en `/`, o ``None``
            para autodetectar `frontend/dist` en el repo.
        auth_enabled: Interruptor del login con Google (opt-in).
        auth_google_client_id: Client ID de la app OAuth de Google.
        auth_google_client_secret: Client secret de la app OAuth de Google.
        auth_allowed_emails: Direcciones habilitadas a entrar (allowlist).
        auth_secret_key: Clave para firmar la cookie de sesion.
        auth_session_max_age: Duracion de la sesion en segundos.
        fiscal_year_default: Anio fiscal por defecto (令和7 = 2025).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "kakuteishinkoku"
    app_version: str = "0.1.0"
    api_prefix: str = "/api/v1"

    database_url: str = Field(
        default="postgresql+psycopg2://kakutei:kakutei@localhost:5440/kakuteishinkoku",
    )

    cors_origins: list[str] = Field(
        default=[
            "http://localhost:5200",
            "http://localhost:5173",
            "http://127.0.0.1:5200",
        ],
    )

    fiscal_year_default: int = 2025

    # --- OCR (Fase 2) ---------------------------------------------------
    # Carpeta donde se archivan las imagenes de recibos (Evidence, 電帳法).
    evidence_dir: str = "data/evidence"

    # --- PWA servida por el backend (un solo origen) ----------------------
    # Carpeta del build del frontend (`npm run build` -> `frontend/dist`). Si
    # existe, el backend la sirve en `/`, asi el celular abre la app y le pega a
    # `/api/v1` del MISMO origen: sin CORS ni URLs configurables. Si no existe
    # (desarrollo), no se monta nada y Vite sigue sirviendo el frontend.
    frontend_dist: str | None = None

    # --- Login con Google (OAuth 2.0) -------------------------------------
    # OPT-IN: apagado por defecto. Sin configurar, la app funciona como siempre
    # (uso local / por tailnet privada, donde no hay a quien autenticar). Se
    # prende cuando el backend queda accesible desde afuera de la red privada.
    #
    # `auth_allowed_emails` es el control de seguridad central: "entrar con
    # Google" NO alcanza — cualquiera tiene una cuenta de Google. Solo las
    # direcciones de esta lista pueden entrar. Sin lista, el login queda
    # DESHABILITADO a proposito (fail-closed): es preferible no arrancar el
    # login a arrancarlo abierto al mundo.
    auth_enabled: bool = False
    auth_google_client_id: str | None = None
    auth_google_client_secret: str | None = None
    auth_allowed_emails: list[str] = Field(default=[])
    # Clave para firmar la cookie de sesion. Sin ella no hay login posible.
    auth_secret_key: str | None = None
    # Duracion de la sesion (default 30 dias: es un uso personal, no un banco).
    auth_session_max_age: int = 60 * 60 * 24 * 30

    # --- 過去の申告 (archivo histórico de declaraciones anteriores) ----------
    # Carpeta donde se guardan los PDFs de 確定申告 de años anteriores subidos por
    # el owner. Privada, en el equipo (gitignored, 電子帳簿保存法: 7 años).
    past_filings_dir: str = "data/past_filings"

    # Consentimiento global: si es False, SOLO se permiten proveedores que no
    # envian el dato fuera del equipo (sends_data_externally=False).
    allow_external_ocr: bool = False

    # Proveedor primario y cadena de fallback (en orden) por nombre.
    ocr_primary: str = "paddle"
    ocr_fallback_chain: list[str] = Field(default=["paddle", "gemini"])

    # Flags on/off por proveedor.
    ocr_paddle_enabled: bool = True
    ocr_azure_enabled: bool = False
    ocr_google_enabled: bool = False
    ocr_gemini_enabled: bool = False
    ocr_glm_enabled: bool = False
    # OCR 100% local via Ollama (VLM de vision). Privado ($0, dato no sale).
    ocr_ollama_enabled: bool = False
    # 'fake' solo para tests/dev; nunca habilitado por defecto en runtime.
    ocr_fake_enabled: bool = False

    # Credenciales / config de proveedores cloud (nunca hardcodear).
    ocr_paddle_lang: str = "japan"
    ocr_azure_endpoint: str | None = None
    ocr_azure_key: str | None = None
    ocr_google_project_id: str | None = None
    ocr_google_location: str | None = None
    ocr_google_processor_id: str | None = None
    ocr_gemini_api_key: str | None = None
    # Modelo de structured output. `gemini-2.5-flash` es estable y probado para
    # JSON tipado (el `gemini-3-flash` "a secas" NO existe con ese nombre). El
    # owner puede ajustarlo via OCR_GEMINI_MODEL (gemini-flash-latest, etc.).
    ocr_gemini_model: str = "gemini-2.5-flash"
    # GLM-OCR (Z.AI API o Ollama local). Reutiliza ZAI_API_KEY si OCR_GLM_API_KEY
    # no esta definido (alias por compatibilidad con el .env del owner).
    ocr_glm_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("ocr_glm_api_key", "zai_api_key"),
    )
    ocr_glm_api_url: str | None = None
    ocr_glm_ollama_url: str | None = None
    ocr_glm_model: str = "glm-ocr"
    # OCR local via Ollama (provider 'ollama'): endpoint + modelo de vision.
    # Default glm-ocr (GLM-OCR 1.1B vision). El owner puede usar otro VLM
    # (minicpm-v, llama3.2-vision, qwen2.5vl) via OCR_OLLAMA_MODEL.
    ocr_ollama_url: str | None = None
    ocr_ollama_model: str = "glm-ocr"

    # --- Preproceso de imagen (mayor salto de precision, research §5.1) ----
    # Aplica deskew/CLAHE/denoise/binarizacion/upscale ANTES de provider.extract.
    # Si OpenCV no esta instalado, degrada con gracia (usa la imagen original).
    ocr_preprocess_enabled: bool = True

    # --- Ensemble / consensus (opt-in, research §5.4) ---------------------
    # Si esta activo y la validacion es bloqueante o la confianza es baja, corre
    # un 2do provider de la cadena y vota campo a campo (consenso anti-alucinacion).
    ocr_ensemble_enabled: bool = False

    # --- Post-correccion LLM (opt-in, research §5.5) ----------------------
    # Si el cuadre aritmetico falla con un provider LLM, re-pregunta una vez
    # mostrando el error. Solo aplica a providers que aceptan re-prompt.
    ocr_postcorrection_enabled: bool = False

    # --- Cuota diaria del free tier de los providers cloud ----------------
    # Cuenta las requests REALES por dia (reset a medianoche US/Pacific, como
    # Google). Al alcanzar el limite, el provider queda no-usable ese dia y el
    # registry lo salta (cae al fallback local). Default CONSERVADOR: el owner lo
    # ajusta a su numero real de aistudio.google.com/rate-limit por modelo.
    ocr_default_daily_limit: int = 200
    ocr_gemini_daily_limit: int | None = None
    ocr_glm_daily_limit: int | None = None
    ocr_azure_daily_limit: int | None = None
    ocr_google_daily_limit: int | None = None


@lru_cache
def get_settings() -> Settings:
    """Devuelve la instancia cacheada de Settings.

    Returns:
        Instancia singleton de `Settings`.
    """
    return Settings()
