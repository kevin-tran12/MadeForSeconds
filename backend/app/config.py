from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    gcp_project_id: str = "madefor-seconds-local"
    environment: str = "development"  # "development" | "production"
    admin_emails: str = "dev@local"  # comma-separated list
    allowed_origins: str = "http://localhost:5173"  # comma-separated list
    gcs_bucket_name: str | None = None
    mcp_api_key: str = ""  # Bearer token for MCP endpoint auth
    redis_url: str | None = None  # e.g. rediss://default:TOKEN@host.upstash.io:6379

    @property
    def admin_email_set(self) -> set[str]:
        return {e.strip() for e in self.admin_emails.split(",") if e.strip()}

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def is_dev(self) -> bool:
        return self.environment == "development"

    model_config = {"env_file": ".env"}


settings = Settings()
