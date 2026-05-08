"""Application settings — single source of truth for environment variables.

References:
  @docs/10-config-and-secrets.md
  @docs/00-scope.md §3.1 (dual-key secret rotation)
  @docs/03-document-pipeline.md §7 (upload environment variables)
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration is read from environment variables or a .env file.

    New fields must be documented in @docs/10-config-and-secrets.md and
    added to .env.example simultaneously.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # General
    # ------------------------------------------------------------------
    log_level: str = "INFO"
    app_version: str = "0.1.0"
    env: str = "dev"

    # ------------------------------------------------------------------
    # Internal auth — dual-key rotation (@docs/00-scope.md §3.1)
    # ------------------------------------------------------------------
    internal_auth_secret_primary: str = ""
    """Primary shared secret for ``X-Internal-Auth`` header validation.

    Must be set in prod.  Empty string disables auth in dev/test
    (the dependency will still call ``constant_time_eq`` — both keys
    empty means any non-empty header fails, so explicitly set to a
    dev placeholder like ``"dev-secret"`` when needed).
    """

    internal_auth_secret_secondary: str = ""
    """Secondary shared secret — active during key rotation.

    When non-empty, *either* primary or secondary is accepted.
    Docs: @docs/00-scope.md §3.1
    """

    # ------------------------------------------------------------------
    # Document upload (@docs/03-document-pipeline.md §7)
    # ------------------------------------------------------------------
    max_upload_bytes: int = 100 * 1024 * 1024  # 100 MB
    """Maximum file size for ``POST /internal/documents/upload``.

    Docs: @docs/03-document-pipeline.md §2.1 / §7
    """

    allowed_mime_types_raw: str = (
        "application/pdf,"
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document,"
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,"
        "text/html"
    )
    """Comma-separated MIME type whitelist stored as a plain string.

    The env var ``ALLOWED_MIME_TYPES`` must use comma-separated values
    without spaces.  Use ``settings.allowed_mime_types`` (the property)
    for the parsed ``tuple[str, ...]``.

    Docs: @docs/03-document-pipeline.md §2.1
    """

    @field_validator("allowed_mime_types_raw", mode="before")
    @classmethod
    def _coerce_mime_types(cls, v: object) -> str:
        """Accept comma-separated string or list/tuple from env."""
        if isinstance(v, (list, tuple)):
            return ",".join(str(item) for item in v)
        return str(v)

    @property
    def allowed_mime_types(self) -> tuple[str, ...]:
        """Return the parsed MIME whitelist as an immutable tuple.

        Returns:
            Tuple of allowed MIME type strings.
        """
        return tuple(m.strip() for m in self.allowed_mime_types_raw.split(",") if m.strip())

    # ------------------------------------------------------------------
    # S3 (@docs/04-data-stores.md §3)
    # ------------------------------------------------------------------
    s3_documents_bucket: str = "witive-docs-dev"
    """S3 bucket for document storage.  Dev default points to a local fake.

    Docs: @docs/04-data-stores.md §3.1
    """

    # ------------------------------------------------------------------
    # SQS (@docs/04-data-stores.md §3.5)
    # ------------------------------------------------------------------
    sqs_indexing_queue_url: str = "fake://indexing"
    """SQS queue URL for document indexing jobs.

    ``fake://`` prefix is the dev/test sentinel that triggers the
    ``FakeSqs`` adapter.  Docs: @docs/03-document-pipeline.md §2.3
    """

    # ------------------------------------------------------------------
    # Job cache (@docs/03-document-pipeline.md §2.3)
    # ------------------------------------------------------------------
    job_cache_ttl_s: int = 5
    """Redis TTL (seconds) for ``job:{job_id}`` cache keys.

    S3 ``jobs/{job_id}.json`` is the single source of truth; Redis is
    an acceleration cache only.  Docs: @docs/03-document-pipeline.md §2.3
    """

    # ------------------------------------------------------------------
    # Level rank override (@docs/07-multitenancy-and-access.md §1.4)
    # ------------------------------------------------------------------
    level_rank_json: str = "{}"
    """JSON string overriding the default ``LEVEL_RANK`` mapping.

    Empty object ``"{}"`` means use the domain default mapping.
    Format: ``{"직급": rank_int, ...}`` where lower rank = lower seniority.
    Docs: @docs/07-multitenancy-and-access.md §1.4
    """


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton Settings instance."""
    return Settings()
