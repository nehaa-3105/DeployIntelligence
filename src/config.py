"""
Configuration module for Deployment Memory.

Loads environment variables from .env (via python-dotenv) and exposes them
as a single typed Settings object. All other modules import from here.

Required:
    HINDSIGHT_API_KEY     — Hindsight Cloud authentication key

Optional:
    HINDSIGHT_BASE_URL    — default: https://api.hindsight.vectorize.io
    HINDSIGHT_BANK_ID     — default: deployment-memory
    GROQ_API_KEY          — used by the analysis LLM agent; optional at import time
    GROQ_MODEL            — default: llama-3.3-70b-versatile
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

        # --- Groq (optional — used by the analysis LLM agent) ---
        self.groq_api_key: str = os.environ.get("GROQ_API_KEY", "")
        self.groq_model: str = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

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
