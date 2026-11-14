"""Settings for Kin. Every key comes from the environment or a .env file; nothing is hard-coded."""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

ROOT = Path(__file__).resolve().parent.parent
KIT = ROOT / "vexo-open-kit"
DB_PATH = Path(os.environ.get("KIN_DB", ROOT / "kin.db"))


def key(name: str) -> str:
    """Returns the key, or '' when it is missing or still the placeholder."""
    v = os.environ.get(name, "").strip()
    return "" if (not v or v.startswith("PLACEHOLDER")) else v


DEEPGRAM_API_KEY = key("DEEPGRAM_API_KEY")
OPENAI_API_KEY = key("OPENAI_API_KEY")
ELEVENLABS_API_KEY = key("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "hpp4J3VqNfWAUOO0d1Us")
GEMINI_API_KEY = key("GEMINI_API_KEY")
STRIPE_SECRET_KEY = key("STRIPE_SECRET_KEY")          # test mode: sk_test_...

OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-6-luna")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-4-hydrogen")

BAND_NUMBER = int(os.environ.get("KIN_BAND", "57"))
WEARER_NAME = os.environ.get("KIN_WEARER", "Grandpa Joe")
SPEND_LIMIT_CENTS = int(os.environ.get("KIN_SPEND_LIMIT_CENTS", "5000"))   # family's per-purchase limit
DASHBOARD_PORT = int(os.environ.get("KIN_PORT", "8700"))
