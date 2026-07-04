"""Settings for data pipelines ETL."""
import os
from functools import lru_cache
from pathlib import Path
import yaml
from pydantic import Field
from pydantic_settings import BaseSettings

class LLMSettings(BaseSettings):
    provider: str = Field(default="anthropic")
    model: str = Field(default="claude-sonnet-4-20250514")
    temperature: float = Field(default=0.1)
    max_tokens: int = Field(default=4096)

class ExtractionSettings(BaseSettings):
    supported_formats: list[str] = Field(default_factory=lambda: ["pdf", "email", "html", "csv"])
    max_document_size_mb: int = Field(default=10)
    batch_size: int = Field(default=10)

class QualitySettings(BaseSettings):
    validation_enabled: bool = Field(default=True)
    completeness_threshold: float = Field(default=0.8)
    accuracy_threshold: float = Field(default=0.9)

class APISettings(BaseSettings):
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000)
    reload: bool = Field(default=False)

class LoggingSettings(BaseSettings):
    level: str = Field(default="INFO")
    format: str = Field(default="json")
    file: str = Field(default="logs/app.log")

class Settings(BaseSettings):
    llm: LLMSettings = Field(default_factory=LLMSettings)
    extraction: ExtractionSettings = Field(default_factory=ExtractionSettings)
    quality: QualitySettings = Field(default_factory=QualitySettings)
    api: APISettings = Field(default_factory=APISettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    anthropic_api_key: str = Field(default="")
    openai_api_key: str = Field(default="")
    model_config = {"env_prefix": "", "env_nested_delimiter": "__"}

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    env = os.getenv("APP_ENV", "development")
    config_dir = Path(__file__).parent.parent.parent.parent / "config"
    env_map = {"development": "dev", "production": "prod"}
    suffix = env_map.get(env, "")
    config_file = config_dir / f"application-{suffix}.yaml" if suffix else config_dir / "application.yaml"
    if not config_file.exists():
        config_file = config_dir / "application.yaml"
    cfg = {}
    if config_file.exists():
        with open(config_file) as f:
            cfg = yaml.safe_load(f) or {}
    return Settings(
        llm=LLMSettings(**cfg.get("llm", {})) if cfg.get("llm") else LLMSettings(),
        extraction=ExtractionSettings(**cfg.get("extraction", {})) if cfg.get("extraction") else ExtractionSettings(),
        quality=QualitySettings(**cfg.get("quality", {})) if cfg.get("quality") else QualitySettings(),
        api=APISettings(**cfg.get("api", {})) if cfg.get("api") else APISettings(),
        logging=LoggingSettings(**cfg.get("logging", {})) if cfg.get("logging") else LoggingSettings(),
    )
