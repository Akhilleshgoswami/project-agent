from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root: .../support-ticket-agent (not dependent on process cwd)
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILE = _PROJECT_ROOT / ".env"

# Load into os.environ so other libs can see it; Settings also reads the file.
load_dotenv(_ENV_FILE, override=False)


def _mask_secret(value: str) -> str:
    if not value:
        return "(empty)"
    if len(value) <= 12:
        return "***"
    return f"{value[:7]}...{value[-4:]} (len={len(value)})"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Leave default empty — pydantic-settings fills from env / .env
    openai_api_key: str = ""
    model_name: str = "gpt-4o-mini"
    # Below this → escalate (no auto-reply)
    confidence_threshold: float = 0.75
    # At/above this (and other safe checks) → auto-approve under --supervision
    auto_approve_threshold: float = 0.90

    # gpt-4o-mini list prices (USD per 1M tokens) as of late 2025
    input_price_per_1m: float = 0.15
    output_price_per_1m: float = 0.60

    def resolved_api_key(self) -> str:
        key = (self.openai_api_key or "").strip()
        if key in {"", "your_api_key", "sk-your-key-here"}:
            return ""
        return key

    def log_env(self) -> None:
        """Print loaded settings (API key masked)."""
        key = self.resolved_api_key()
        print("=== Settings / env ===")
        print(f"  env_file:                 {_ENV_FILE} (exists={_ENV_FILE.exists()})")
        print(f"  OPENAI_API_KEY:           {_mask_secret(key)}")
        print(f"  MODEL_NAME:               {self.model_name}")
        print(f"  CONFIDENCE_THRESHOLD:     {self.confidence_threshold}")
        print(f"  AUTO_APPROVE_THRESHOLD:   {self.auto_approve_threshold}")
        print(f"  input_price_per_1m:       {self.input_price_per_1m}")
        print(f"  output_price_per_1m:      {self.output_price_per_1m}")
        print("======================")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.log_env()
    return settings
