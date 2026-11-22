"""Settings for the Diagnosia backend, read from the environment or a .env file."""
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT_DIR / "web"  # the only folder served to the public
STORAGE_DIR = ROOT_DIR / "backend" / "storage"

load_dotenv(ROOT_DIR / ".env")


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _demo_mode(value) -> bool:
    if value is None or not value.strip():
        return os.environ.get("DIAGNOSIA_ENV", "development") == "development"
    return value.strip().lower() not in ("0", "false", "no", "off")


def _prices(text: str) -> dict:
    try:
        table = json.loads(text) if text.strip() else {}
    except ValueError:
        return {}
    return {
        str(model): (float(price[0]), float(price[1]))
        for model, price in table.items()
        if isinstance(price, (list, tuple)) and len(price) == 2
    } if isinstance(table, dict) else {}


def _real_key(value: str) -> str:
    return "" if not value or "your" in value.lower() else value


@dataclass
class Settings:
    db_path: Path = field(
        default_factory=lambda: Path(os.environ.get("DIAGNOSIA_DB", STORAGE_DIR / "diagnosia.db"))
    )
    # How long a write waits for another writer before giving up with "the system is busy" (a 503).
    db_busy_seconds: float = field(default_factory=lambda: float(os.environ.get("DIAGNOSIA_DB_BUSY_SECONDS", "5")))
    documents_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("DIAGNOSIA_DOCUMENTS", STORAGE_DIR / "documents"))
    )
    # The list medicine names are checked against. Never in git: see agent_context.md, Licences.
    medicine_list: Path = field(
        default_factory=lambda: Path(
            os.environ.get("DIAGNOSIA_MEDICINE_LIST")
            or ROOT_DIR / "datasets" / "medicines" / "indian-medicine-dataset" / "DATA" / "indian_medicine_data.csv"
        )
    )
    # A JSON key ring kept outside the repository and away from the documents. See vault.py.
    document_key_file: str = field(default_factory=lambda: os.environ.get("DIAGNOSIA_DOCUMENT_KEY_FILE", ""))
    # development, staging or production. Anything unknown counts as production.
    environment: str = field(default_factory=lambda: os.environ.get("DIAGNOSIA_ENV", "development"))
    # Safety switches. Each is off unless set to exactly 1, and pilot mode is on unless set to exactly 0.
    # Turning one on does nothing by itself: see safety.py for what each one also requires.
    clinical_pilot_mode: bool = field(default_factory=lambda: os.environ.get("CLINICAL_PILOT_MODE") != "0")
    allow_real_patient_data: bool = field(default_factory=lambda: os.environ.get("ALLOW_REAL_PATIENT_DATA") == "1")
    default_consent: bool = field(default_factory=lambda: os.environ.get("DIAGNOSIA_DEFAULT_CONSENT", "1").strip() != "0")
    enable_external_messaging: bool = field(default_factory=lambda: os.environ.get("ENABLE_EXTERNAL_MESSAGING") == "1")
    # Set DIAGNOSIA_HTTPS=1 in production so session cookies are HTTPS-only.
    cookie_secure: bool = field(default_factory=lambda: os.environ.get("DIAGNOSIA_HTTPS") == "1")
    # A signed-in session ends after this many minutes with no activity (background polling doesn't
    # count). 0 turns the idle limit off; the absolute lifetime in auth.py still applies.
    session_idle_minutes: int = field(default_factory=lambda: int(os.environ.get("DIAGNOSIA_SESSION_IDLE_MINUTES", "30")))
    # A self-service kiosk sends new visits only to this verified doctor's queue.
    diagnofast_kiosk_doctor_id: str = field(default_factory=lambda: os.environ.get("DIAGNOFAST_KIOSK_DOCTOR_ID", ""))
    # An interview link that is never opened stops working after this. Once started, the patient has the
    # second window to finish. Both are hours.
    diagnofast_link_hours: int = field(default_factory=lambda: int(os.environ.get("DIAGNOSIA_DIAGNOFAST_LINK_HOURS", "24")))
    diagnofast_interview_hours: int = field(default_factory=lambda: int(os.environ.get("DIAGNOSIA_DIAGNOFAST_INTERVIEW_HOURS", "2")))
    # The deployment's daily AI breaker (UTC days). 0 turns a cap off. Spend needs DIAGNOSIA_AI_PRICES:
    # a JSON object of model -> [US dollars per million input tokens, per million output tokens].
    ai_daily_tokens: int = field(default_factory=lambda: int(os.environ.get("DIAGNOSIA_AI_DAILY_TOKENS", "5000000")))
    ai_daily_spend_usd: float = field(default_factory=lambda: float(os.environ.get("DIAGNOSIA_AI_DAILY_SPEND_USD", "0")))
    ai_prices: dict = field(default_factory=lambda: _prices(os.environ.get("DIAGNOSIA_AI_PRICES", "")))
    # Edge neural voices send the question text to Microsoft with no agreement, so they only ever run in
    # demo mode with made-up patients (see neural_tts_allowed). DIAGNOSIA_NEURAL_TTS=0 turns them off there too.
    neural_tts_enabled: bool = field(default_factory=lambda: os.environ.get("DIAGNOSIA_NEURAL_TTS", "1") != "0")
    # The only AI hosts patient text may go to. A local model on this machine keeps the data here.
    allowed_ai_hosts: tuple = field(default_factory=lambda: tuple(
        host.strip().lower()
        for host in os.environ.get(
            "DIAGNOSIA_ALLOWED_AI_HOSTS", "api.groq.com,generativelanguage.googleapis.com,api.sarvam.ai,localhost,127.0.0.1"
        ).split(",")
        if host.strip()
    ))
    # A real key, or leave empty and add one in Settings. Placeholders count as empty.
    groq_api_key: str = field(default_factory=lambda: _real_key(os.environ.get("GROQ_API_KEY", "")))
    # A second provider, used as a fallback or in turn. Its OpenAI-compatible endpoint is the default.
    gemini_api_key: str = field(default_factory=lambda: _real_key(os.environ.get("GEMINI_API_KEY", "")))
    gemini_base_url: str = field(
        default_factory=lambda: os.environ.get(
            "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai"
        ).rstrip("/")
    )
    # Sarvam AI, for Hindi and English speech and translation (docs/integrations/SARVAM.md). Used only when
    # the Settings switch is on, the sarvam_terms sign-off is recorded, and real patient data is not allowed.
    sarvam_api_key: str = field(default_factory=lambda: _real_key(os.environ.get("SARVAM_API_KEY", "")))
    sarvam_base_url: str = field(default_factory=lambda: os.environ.get("SARVAM_BASE_URL", "https://api.sarvam.ai").rstrip("/"))
    # Neo4j, a read-only copy for DiagnoFast's graphs (docs/integrations/NEO4J.md). SQLite stays the record.
    neo4j_uri: str = field(default_factory=lambda: os.environ.get("NEO4J_URI", "").strip())
    neo4j_user: str = field(default_factory=lambda: os.environ.get("NEO4J_USER", "neo4j").strip())
    neo4j_api_key: str = field(default_factory=lambda: _real_key(os.environ.get("NEO4J_PASSWORD", "")))  # the password
    neo4j_database: str = field(default_factory=lambda: os.environ.get("NEO4J_DATABASE", "neo4j").strip())
    # Optional integrations. Each is off unless set to exactly 1, and none is needed to run the app.
    # Demo mode is on by default only for development. Anywhere else it needs DIAGNOSIA_DEMO_MODE=1 and also
    # DIAGNOSIA_DEMO_OUTSIDE_DEVELOPMENT=1, or the app refuses to start (safety.assert_safe_to_start).
    demo_mode: bool = field(default_factory=lambda: _demo_mode(os.environ.get("DIAGNOSIA_DEMO_MODE")))
    demo_outside_development: bool = field(default_factory=lambda: _flag("DIAGNOSIA_DEMO_OUTSIDE_DEVELOPMENT"))
    mongodb_enabled: bool = field(default_factory=lambda: _flag("ENABLE_MONGODB_ATLAS_INTEGRATION"))
    mongodb_uri: str = field(default_factory=lambda: _real_key(os.environ.get("MONGODB_ATLAS_URI", "")))
    mongodb_database: str = field(default_factory=lambda: os.environ.get("MONGODB_DATABASE_NAME") or os.environ.get("MONGODB_DATABASE") or "diagnosia_atlas")
    mongodb_timeout_ms: int = field(default_factory=lambda: int(os.environ.get("MONGODB_SERVER_SELECTION_TIMEOUT_MS", "5000")))
    mongodb_change_streams: bool = field(default_factory=lambda: _flag("ENABLE_MONGODB_CHANGE_STREAMS"))
    mongodb_change_stream_collection: str = field(default_factory=lambda: os.environ.get("MONGODB_CHANGE_STREAM_COLLECTION", "care_events"))
    yugabyte_enabled: bool = field(default_factory=lambda: _flag("ENABLE_YUGABYTEDB_INTEGRATION"))
    yugabyte_dsn: str = field(default_factory=lambda: _real_key(os.environ.get("YUGABYTEDB_YSQL_DSN", "")))
    yugabyte_pool_max: int = field(default_factory=lambda: int(os.environ.get("YUGABYTEDB_POOL_MAX_SIZE", "4")))
    meko_enabled: bool = field(default_factory=lambda: _flag("ENABLE_MEKO_INTEGRATION"))
    meko_api_key: str = field(default_factory=lambda: _real_key(os.environ.get("MEKO_API_KEY", "")))
    meko_datapack_id: str = field(default_factory=lambda: os.environ.get("MEKO_DATAPACK_ID", ""))
    meko_url: str = field(default_factory=lambda: os.environ.get("MEKO_MCP_URL", "https://mcp.mekodata.ai/mcp"))
    meko_patient_packs_enabled: bool = field(default_factory=lambda: _flag("ENABLE_MEKO_PATIENT_PACKS"))
    # Deleting a datapack doesn't return its slot, so creations are capped well below the plan's limit.
    meko_pack_limit: int = field(default_factory=lambda: int(os.environ.get("MEKO_PACK_LIMIT", "6")))
    event_batch_size: int = field(default_factory=lambda: int(os.environ.get("EVENT_DELIVERY_BATCH_SIZE", "50")))
    event_max_attempts: int = field(default_factory=lambda: int(os.environ.get("EVENT_DELIVERY_MAX_ATTEMPTS", "8")))
    event_backoff_seconds: int = field(default_factory=lambda: int(os.environ.get("EVENT_DELIVERY_BACKOFF_SECONDS", "30")))
    ai_base_url: str = field(
        default_factory=lambda: os.environ.get("AI_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")
    )


settings = Settings()


def neural_tts_allowed() -> bool:
    return settings.neural_tts_enabled and settings.demo_mode and not settings.allow_real_patient_data
