"""Application configuration loaded once from environment variables.

All env-var access in the codebase MUST go through this module.
Never call os.environ.get() in service files (system prompt Rule 8).
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # --- Database ---
    DATABASE_URL: str

    # --- Redis ---
    REDIS_URL: str

    # --- Auth ---
    JWT_SECRET_KEY: str
    SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60 * 24

    # --- Groq ---
    GROQ_API_KEY: str = ""
    GROQ_BASE_URL: str = "https://api.groq.com"

    # --- Backblaze B2 ---
    BACKBLAZE_KEY_ID: str = ""
    BACKBLAZE_APP_KEY: str = ""
    BACKBLAZE_BUCKET: str = ""

    # --- ML / pipeline tunables ---
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    DRIFT_THRESHOLD: float = 0.25
    COGNITIVE_LOAD_THRESHOLD: int = 6

    # --- HTTP / CORS ---
    CORS_ORIGINS: str = "http://localhost:3000"

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
