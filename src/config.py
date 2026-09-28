"""
Configuration module for Deployment Memory.

Loads environment variables from .env (via python-dotenv) and exposes them
as a single typed Settings object. All other modules import from here.

Required:
    HINDSIGHT_API_KEY     — Hindsight Cloud authentication key

Optional:
    HINDSIGHT_BASE_URL    — default: https://api.hindsight.vectorize.io
    HINDSIGHT_BANK_ID     — default: deployment-memory
    OPENAI_API_KEY        — needed only when the LLM agent runs
    OPENAI_MODEL          — default: gpt-4o
    GEMINI_API_KEY        — not used by the API path; optional
    GEMINI_MODEL          — default: gemini-2.5-flash
    DATA_DIR              — directory for the JSON ledger; default: ./data
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    """
    Typed container for all runtime configuration.

    Only HINDSIGHT_API_KEY is mandatory; everything else has a sensible
    default or is truly optional (raises AttributeError if accessed when
    not set, so callers that need it discover the gap immediately).
    """

    def __init__(self) -> None:
        # --- Hindsight (required) ---
        self.hindsight_api_key: str = self._require("HINDSIGHT_API_KEY")
        self.hindsight_base_url: str = os.environ.get(
            "HINDSIGHT_BASE_URL", "https://api.hindsight.vectorize.io"
        )
        self.hindsight_bank_id: str = os.environ.get(
            "HINDSIGHT_BANK_ID", "deployment-memory"
        )

        # --- OpenAI (optional — only needed for LLM agent) ---
        self.openai_api_key: str = os.environ.get("OPENAI_API_KEY", "")
        self.openai_model: str = os.environ.get("OPENAI_MODEL", "gpt-4o")

        # --- Gemini (optional — not used by the API path) ---
        self.gemini_api_key: str = os.environ.get("GEMINI_API_KEY", "")
        self.gemini_model: str = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

        # --- Ledger ---
        self.data_dir: str = os.environ.get("DATA_DIR", "./data")

    @staticmethod
    def _require(key: str) -> str:
        """Return the value of an env var or raise with a clear message."""
        value = os.environ.get(key, "").strip()
        if not value:
            raise ValueError(
                f"Required environment variable '{key}' is not set. "
                "Copy .env.example to .env and fill in your credentials."
            )
        return value


# Module-level singleton — import this everywhere.
settings = Settings()
