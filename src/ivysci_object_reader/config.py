"""Configuration objects supplied by the host application."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class AliyunCredentials:
    """Credentials used to create Aliyun OSS clients.

    Values are excluded from ``repr`` so logging a reader cannot leak them.
    """

    access_key_id: str = field(repr=False)
    access_key_secret: str = field(repr=False)

    def __post_init__(self) -> None:
        if not self.access_key_id:
            raise ValueError("access_key_id is required")
        if not self.access_key_secret:
            raise ValueError("access_key_secret is required")


@dataclass(frozen=True, slots=True)
class StorageConfig:
    """Connection and CDN settings for one OSS bucket."""

    bucket_name: str
    region: str = "cn-shanghai"
    cdn_base_url: str | None = None
    cdn_proxy_base_url: str | None = None
    # Nginx routing prefix. Distinct from the application storage name so a
    # shared proxy can tell production `/default/` from testing `/default-testing/`.
    cdn_proxy_prefix: str | None = None
    cdn_auth_key: str | None = field(default=None, repr=False)
    cdn_url_ttl: int | None = None

    def __post_init__(self) -> None:
        if not self.bucket_name:
            raise ValueError("bucket_name is required")
        if not self.region:
            raise ValueError("region is required")
        if self.cdn_proxy_prefix is not None:
            prefix = self.cdn_proxy_prefix.strip("/")
            if not prefix:
                raise ValueError("cdn_proxy_prefix must not be empty")
            object.__setattr__(self, "cdn_proxy_prefix", prefix)
        if self.cdn_auth_key and not self.cdn_url_ttl:
            raise ValueError("cdn_url_ttl is required when cdn_auth_key is set")
        if self.cdn_url_ttl is not None and self.cdn_url_ttl <= 0:
            raise ValueError("cdn_url_ttl must be greater than zero")

    @property
    def endpoint(self) -> str:
        return f"oss-{self.region}.aliyuncs.com"

    @property
    def internal_endpoint(self) -> str:
        return f"oss-{self.region}-internal.aliyuncs.com"
