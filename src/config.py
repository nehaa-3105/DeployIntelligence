"""
Configuration module for Deployment Memory.

Loads all required environment variables from .env (via python-dotenv)
and exposes them as a single typed Settings object. All other modules
import from here — no module reads os.environ directly.

Environment variables required:
    HINDSIGHT_API_KEY     — Hindsight Cloud authentication key
    HINDSIGHT_BASE_URL    — Hindsight API base URL (default: https://api.hindsight.vectorize.io)
    HINDSIGHT_BANK_ID     — Memory bank scoped to this project (default: deployment-memory)
    OPENAI_API_KEY        — OpenAI authentication key
    OPENAI_MODEL          — Model name to use for analysis (default: gpt-4o)
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    """
    Typed container for all runtime configuration.
    Raises ValueError at construction time if required variables are missing,
    so misconfiguration surfaces immediately on startup rather than mid-run.
    """

    def __init__(self) -> None:
        # --- Hindsight ---
        self.hindsight_api_key: str = self._require("HINDSIGHT_API_KEY")
        self.hindsight_base_url: str = os.environ.get(
            "HINDSIGHT_BASE_URL", "https://api.hindsight.vectorize.io"
        )
        self.hindsight_bank_id: str = os.environ.get(
            "HINDSIGHT_BANK_ID", "deployment-memory"
        )

        # --- OpenAI ---
        self.openai_api_key: str = self._require("OPENAI_API_KEY")
        self.openai_model: str = os.environ.get("OPENAI_MODEL", "gpt-4o")

    @staticmethod
    def _require(key: str) -> str:
        """Return the value of an environment variable or raise if absent/empty."""
        value = os.environ.get(key, "").strip()
        if not value:
            raise ValueError(
                f"Required environment variable '{key}' is not set. "
                "Copy .env.example to .env and fill in your credentials."
            )
        return value


# Module-level singleton — import this everywhere.
settings = Settings()
