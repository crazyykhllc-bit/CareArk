from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "个人健康档案工作台"
    environment: str = "development"
    database_url: str = "sqlite+aiosqlite:///./health_archive.db"

    s3_endpoint: str = "localhost:9000"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = "health-archive"
    s3_secure: bool = False
    storage_backend: str = "minio"
    file_storage_root: str = ""

    model_provider: str = "openai-compatible"
    model_base_url: str = "https://api.openai.com/v1"
    model_api_key: str = ""
    model_name: str = ""
    model_fallback_base_url: str = ""
    model_fallback_api_key: str = ""
    model_fallback_name: str = ""
    model_fallback2_base_url: str = ""
    model_fallback2_api_key: str = ""
    model_fallback2_name: str = ""
    model_fallback2_strict_json_schema: bool = False
    model_strict_json_schema: bool = True
    model_timeout_seconds: int = Field(default=120, ge=5, le=600)
    model_max_retries: int = Field(default=3, ge=0, le=10)
    model_max_pages: int = Field(default=30, ge=1, le=200)
    model_image_detail: str = "high"
    model_stream_responses: bool = True

    session_cookie_name: str = "health_session"
    session_hours: int = Field(default=168, ge=1, le=720)
    secure_cookies: bool = False
    upload_max_bytes: int = Field(default=25 * 1024 * 1024, ge=1024)
    worker_poll_seconds: float = Field(default=2.0, ge=0.1, le=60)
    batch_max_files: int = Field(default=20, ge=1, le=100)
    batch_max_bytes: int = Field(default=100 * 1024 * 1024, ge=1024)
    model_max_request_bytes: int = Field(default=40 * 1024 * 1024, ge=1024)
    model_merge_max_sources_per_request: int = Field(default=5, ge=1, le=20)
    model_max_sources_per_request: int = Field(default=1, ge=1, le=20)
    model_batch_concurrency: int = Field(default=2, ge=1, le=8)
    model_chunk_max_output_tokens: int = Field(default=4000, ge=1000)
    model_max_output_tokens: int = Field(default=16000, ge=1000)
    model_output_token_parameter: str = 'max_tokens'


@lru_cache
def get_settings() -> Settings:
    return Settings()
