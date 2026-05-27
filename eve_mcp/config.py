"""Runtime configuration loaded from environment variables."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="EVE_MCP_",
        extra="ignore",
    )

    sde_path: Path = Field(
        default=Path("data/sde.sqlite"),
        description="Path to the SQLite SDE database.",
    )
    price_cache_path: Path = Field(
        default=Path("data/price_cache.sqlite"),
        description="Path to the ESI price cache SQLite file.",
    )
    price_cache_ttl_seconds: int = Field(
        default=1800,
        description="How long a cached price is considered fresh.",
    )
    esi_base_url: str = Field(
        default="https://esi.evetech.net/latest",
        description="Base URL for the EVE Swagger Interface.",
    )
    esi_market_region_id: int = Field(
        default=10000002,
        description="Region ID for market price lookups (default: The Forge / Jita).",
    )
    host: str = Field(default="0.0.0.0", description="MCP server bind host.")
    port: int = Field(default=8080, description="MCP server bind port.")


settings = Settings()
