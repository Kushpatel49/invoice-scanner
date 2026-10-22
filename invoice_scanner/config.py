"""Settings. Company- and deployment-specific values come from environment
variables (or a .env file in the working directory / repo root); the defaults
below are for Greens Angaadi Agro Pvt Ltd."""
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_env(*paths):
    """Minimal .env loader (KEY=value lines). Real environment variables win."""
    for path in paths or (Path.cwd() / ".env", REPO_ROOT / ".env"):
        if path.exists():
            for line in path.read_text().splitlines():
                k, _, v = line.partition("=")
                if k.strip() and not k.lstrip().startswith("#"):
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env()

# --- Our company: the buyer on every purchase bill ---------------------------
COMPANY_NAME = os.environ.get("COMPANY_NAME", "Greens Angaadi Agro Pvt Ltd")
COMPANY_GSTIN = os.environ.get("COMPANY_GSTIN", "32AAHCG9621M1ZC")
# Other names suppliers write for us; helps the model tell buyer from supplier.
COMPANY_ALIASES = os.environ.get("COMPANY_ALIASES", "Greens Angadi, Aeden Fresh, Kakkanad")

# --- Models -------------------------------------------------------------------
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/chat")
MODELS = {
    "openrouter": os.environ.get("OPENROUTER_MODEL", "nvidia/nemotron-3.5-super-vl"),
    # The plain qwen3-vl:8b tag reasons for minutes before answering; use the instruct tag.
    "ollama": os.environ.get("OLLAMA_MODEL", "qwen3-vl:8b-instruct"),
}


def default_backend():
    return os.environ.get("SCANNER_BACKEND") or ("openrouter" if os.environ.get("OPENROUTER_API_KEY") else "ollama")


# --- Extraction ---------------------------------------------------------------
MAX_SIDE = 1600                     # longest image side sent to the model, px
GST_RATES = (0, 3, 5, 12, 18, 28)   # line amounts may be tax-inclusive at any of these
