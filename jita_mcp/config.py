"""Runtime configuration loaded from environment variables."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="JITA_MCP_",
        extra="ignore",
    )

    sde_path: Path = Field(
        default=Path("data/sde.sqlite"),
        description="Path to the Fuzzwork SQLite SDE (used by Fuzzwork-backed tools).",
    )
    host: str = Field(default="0.0.0.0", description="MCP server bind host.")
    port: int = Field(default=8080, description="MCP server bind port.")


settings = Settings()
