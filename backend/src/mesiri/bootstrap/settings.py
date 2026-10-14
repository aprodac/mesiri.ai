"""Centralized configuration and secret loading (M1).

One settings object, loaded from environment variables (prefix ``MESIRI_``,
nested delimiter ``__``) and an optional ``.env`` file. Safe defaults exist for
local development only; :meth:`Settings.validate_runtime` fails fast when
required production configuration is missing.

Secrets live only in ``SecretStr`` fields and are never emitted by ``repr`` or
by the logging/health redaction paths.

Ownership: SHARED ARCHITECTURE.
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache

from pydantic import BaseModel, ConfigDict, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from mesiri_contracts.common.errors import ErrorCode, MesiriError


class Environment(str, Enum):
    LOCAL = "local"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"

    @property
    def is_production_like(self) -> bool:
        return self in (Environment.STAGING, Environment.PRODUCTION)


class LogFormat(str, Enum):
    JSON = "json"
    CONSOLE = "console"


class _Section(BaseModel):
    # Plain BaseModel — NOT BaseSettings. Nested settings are populated by the
    # root Settings via env_nested_delimiter (MESIRI_POSTGRES__USER). If these
    # were BaseSettings they would each independently read *unprefixed* env vars
    # (e.g. $USER on Linux -> postgres.user), which is a cross-platform trap.
    model_config = ConfigDict(extra="ignore")


class LogSettings(_Section):
    level: str = "INFO"
    format: LogFormat = LogFormat.JSON


class PostgresSettings(_Section):
    host: str = "localhost"
    port: int = 5432
    user: str = "mesiri"
    password: SecretStr = SecretStr("mesiri_local_dev")
    database: str = "mesiri"
    pool_min_size: int = 1
    pool_max_size: int = 10
    connect_timeout_seconds: float = 5.0

    def dsn(self, *, driver: str = "postgresql+asyncpg") -> str:
        pwd = self.password.get_secret_value()
        return f"{driver}://{self.user}:{pwd}@{self.host}:{self.port}/{self.database}"

    def safe_dsn(self) -> str:
        """DSN with the password redacted — safe for logs."""
        return f"postgresql://{self.user}:***@{self.host}:{self.port}/{self.database}"


class RedisSettings(_Section):
    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: SecretStr | None = None
    namespace: str = "mesiri"
    connect_timeout_seconds: float = 5.0

    def url(self) -> str:
        auth = ""
        if self.password is not None:
            auth = f":{self.password.get_secret_value()}@"
        return f"redis://{auth}{self.host}:{self.port}/{self.db}"

    def safe_url(self) -> str:
        auth = ":***@" if self.password is not None else ""
        return f"redis://{auth}{self.host}:{self.port}/{self.db}"


class ObjectStorageProvider(str, Enum):
    FAKE = "fake"
    R2 = "r2"
    LOCAL = "local"


class ObjectStorageSettings(_Section):
    provider: ObjectStorageProvider = ObjectStorageProvider.FAKE
    bucket: str = "mesiri-media-local"
    endpoint_url: str | None = None
    access_key_id: SecretStr | None = None
    secret_access_key: SecretStr | None = None
    region: str = "auto"
    presign_ttl_seconds: int = 900
    # provider=local: files live under local_root on this server and are served
    # by the app's own /media route, at public_base_url, via signed links.
    local_root: str = "/var/lib/mesiri/media"
    public_base_url: str | None = None
    signing_secret: SecretStr | None = None


class SarvamSettings(_Section):
    api_key: SecretStr | None = None
    timeout_seconds: float = 7.0
    # 2 retries = 3 attempts = up to 21s on a hung transcription call (7s
    # timeout × 3). 1 retry caps the same failure mode at 14s while still
    # absorbing a single transient blip, matching GeminiSettings' policy.
    max_retries: int = 1


class GeminiSettings(_Section):
    api_key: SecretStr | None = None
    model: str = "gemini-2.5-flash"
    # Photos are downscaled to this longest edge before the vision call (see
    # the Gemini adapter's _downscale_image). Env-tunable on purpose: the
    # right value is empirical -- lower is faster and cheaper, but handwritten
    # attendance sheets need enough resolution to stay legible, so it can be
    # trialled against real photos without a code change. 0 disables it.
    max_image_edge: int = 1568
    timeout_seconds: float = 15.0
    # 2 retries = 3 attempts = up to 45s on a hung call before the user sees
    # anything -- traced worst-case messages this week hit that ceiling
    # (48.4s max on `understanding`, 73.2s wall-clock overall). 1 retry caps
    # the same failure mode at 30s while still absorbing a single transient
    # blip.
    max_retries: int = 1


class DeepSeekSettings(_Section):
    api_key: SecretStr | None = None
    # deepseek-chat stopped resolving 24 Jul 2026 (BE-29; mesiri_ai/model_names.py).
    model: str = "deepseek-flash"
    base_url: str = "https://api.deepseek.com"
    timeout_seconds: float = 30.0
    max_retries: int = 2


class WhatsAppSettings(_Section):
    # Owned by M2 (Alan); declared for completeness. Unused by M1/M3.
    verify_token: SecretStr | None = None
    app_secret: SecretStr | None = None
    access_token: SecretStr | None = None
    phone_number_id: str | None = None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MESIRI_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Environment = Environment.LOCAL
    service_name: str = "mesiri-assistant"

    #: Opt-in switch for destructive Labour cleanup (MESIRI_ALLOW_LABOUR_DELETE).
    #:
    #: Off by default, which is the whole point: deleting a confirmed attendance
    #: report contradicts the module's own rule that attendance is immutable
    #: (plan principle P5), and the dashboard a developer would click it in is
    #: the same build customers use. Shipping the endpoint disabled means the
    #: code can deploy everywhere while only answering where someone has
    #: deliberately turned it on.
    #:
    #: Intended for clearing test data between runs, never for correcting a
    #: mistake -- a supervisor who mis-reported re-sends the day and chooses
    #: "Replace", which supersedes the old report while keeping it auditable.
    allow_labour_delete: bool = False

    log: LogSettings = Field(default_factory=LogSettings)
    postgres: PostgresSettings = Field(default_factory=PostgresSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    object_storage: ObjectStorageSettings = Field(default_factory=ObjectStorageSettings)
    sarvam: SarvamSettings = Field(default_factory=SarvamSettings)
    gemini: GeminiSettings = Field(default_factory=GeminiSettings)
    deepseek: DeepSeekSettings = Field(default_factory=DeepSeekSettings)
    whatsapp: WhatsAppSettings = Field(default_factory=WhatsAppSettings)

    def validate_runtime(self) -> None:
        """Fail fast for missing *required* production configuration.

        Local/test may rely on safe defaults and the fake object store; a
        production-like environment must supply real secrets and, when R2 is
        selected, complete storage credentials.
        """
        if not self.environment.is_production_like:
            return

        missing: list[str] = []
        default_pg = "mesiri_local_dev"
        if self.postgres.password.get_secret_value() == default_pg:
            missing.append("MESIRI_POSTGRES__PASSWORD (still the local default)")

        if self.object_storage.provider is ObjectStorageProvider.FAKE:
            missing.append("MESIRI_OBJECT_STORAGE__PROVIDER (fake not allowed in production)")
        elif self.object_storage.provider is ObjectStorageProvider.R2:
            for name, val in (
                ("MESIRI_OBJECT_STORAGE__ENDPOINT_URL", self.object_storage.endpoint_url),
                ("MESIRI_OBJECT_STORAGE__ACCESS_KEY_ID", self.object_storage.access_key_id),
                ("MESIRI_OBJECT_STORAGE__SECRET_ACCESS_KEY", self.object_storage.secret_access_key),
            ):
                if not val:
                    missing.append(name)
        elif self.object_storage.provider is ObjectStorageProvider.LOCAL:
            for name, val in (
                ("MESIRI_OBJECT_STORAGE__PUBLIC_BASE_URL", self.object_storage.public_base_url),
                ("MESIRI_OBJECT_STORAGE__SIGNING_SECRET", self.object_storage.signing_secret),
            ):
                if not val:
                    missing.append(name)

        if missing:
            raise MesiriError.configuration(
                f"missing required production configuration: {', '.join(missing)}",
                code=ErrorCode.CONFIG_MISSING.value,
                details={"missing": missing, "environment": self.environment.value},
            )


@lru_cache
def get_settings() -> Settings:
    """Process-wide cached settings instance."""
    return Settings()
