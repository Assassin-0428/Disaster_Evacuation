"""
Central config, loaded once from environment variables (.env file
locally, or Render's injected environment variables in production).
"""
import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "disaster_evac_planner"
    db_user: str = "postgres"
    db_password: str = ""

    openweather_api_key: str = ""
    weather_poll_interval_minutes: int = 15

    admin_username: str = "admin"
    admin_password: str = "ChangeMe123!"

    @property
    def database_url(self) -> str:
        # Render (and most cloud hosts) provide a single DATABASE_URL
        # env var directly — prefer that if present, and it needs SSL.
        render_db_url = os.environ.get("DATABASE_URL")
        if render_db_url:
            url = render_db_url.replace("postgres://", "postgresql+psycopg2://", 1)
            if "sslmode" not in url:
                url += "?sslmode=require" if "?" not in url else "&sslmode=require"
            return url

        # Local development: plain local Postgres, no SSL required.
        return (
            f"postgresql+psycopg2://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    class Config:
        env_file = ".env"


settings = Settings()