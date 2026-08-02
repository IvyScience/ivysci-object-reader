"""Runtime-aware object downloads with CDN-to-OSS fallback."""

from __future__ import annotations

import datetime as dt
import logging
import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urljoin
from zoneinfo import ZoneInfo

import httpx
import oss2

from .config import AliyunCredentials, StorageConfig
from .signing import auth_b

logger = logging.getLogger(__name__)

BucketFactory = Callable[[StorageConfig, bool], Any]


class ObjectReader:
    """Read objects using unob's existing runtime routing policy.

    Routing is intentionally simple:

    * ``use_internal_endpoint``: read directly from the internal OSS endpoint.
    * otherwise, when ``prefer_cdn`` is true: use the configured internal CDN
      proxy when present, or the public CDN; non-404 HTTP failures fall back to
      the public OSS endpoint.
    * otherwise: read directly from the public OSS endpoint.

    The host application owns configuration loading. This class never reads
    Django settings, YAML files, or environment variables.
    """

    def __init__(
        self,
        *,
        credentials: AliyunCredentials,
        storages: Mapping[str, StorageConfig],
        cdn_proxy_base_url: str | None = None,
        use_internal_endpoint: bool = False,
        prefer_cdn: bool = True,
        signing_timezone: str | dt.tzinfo = "Asia/Shanghai",
        http_client: httpx.Client | None = None,
        bucket_factory: BucketFactory | None = None,
    ) -> None:
        if not storages:
            raise ValueError("at least one storage is required")
        self._credentials = credentials
        self._storages = dict(storages)
        self.cdn_proxy_base_url = cdn_proxy_base_url
        self.use_internal_endpoint = use_internal_endpoint
        self.prefer_cdn = prefer_cdn
        self._timezone = (
            ZoneInfo(signing_timezone)
            if isinstance(signing_timezone, str)
            else signing_timezone
        )
        self._client = http_client or httpx.Client(
            follow_redirects=True,
            timeout=httpx.Timeout(120, connect=10),
        )
        self._owns_http_client = http_client is None
        self._bucket_factory = bucket_factory or self._create_bucket

    def __enter__(self) -> ObjectReader:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_http_client:
            self._client.close()

    def get_storage(self, storage_name: str = "default") -> StorageConfig:
        try:
            return self._storages[storage_name]
        except KeyError as exc:
            raise KeyError(f"unknown storage: {storage_name!r}") from exc

    def _create_bucket(self, storage: StorageConfig, internal: bool) -> oss2.Bucket:
        auth = oss2.AuthV4(
            self._credentials.access_key_id,
            self._credentials.access_key_secret,
        )
        endpoint = storage.internal_endpoint if internal else storage.endpoint
        return oss2.Bucket(
            auth,
            endpoint,
            storage.bucket_name,
            region=storage.region,
        )

    def get_bucket(
        self, storage_name: str = "default", *, internal: bool | None = None
    ) -> Any:
        if internal is None:
            internal = self.use_internal_endpoint
        return self._bucket_factory(self.get_storage(storage_name), internal)

    def _signed_path(
        self,
        storage: StorageConfig,
        key: str,
        ttl: int | None,
    ) -> str:
        if not storage.cdn_auth_key:
            return key
        effective_ttl = ttl or storage.cdn_url_ttl
        if effective_ttl is None:
            raise ValueError("cdn_url_ttl is required when cdn_auth_key is set")
        expires_at = dt.datetime.now(self._timezone) + dt.timedelta(
            seconds=effective_ttl
        )
        return auth_b(storage.cdn_auth_key, key, expires_at)

    @staticmethod
    def _join_url(base_url: str, path: str) -> str:
        return urljoin(f"{base_url.rstrip('/')}/", path.lstrip("/"))

    @staticmethod
    def _with_query(url: str, query: Mapping[str, Any] | None) -> str:
        if not query:
            return url
        return f"{url}?{urlencode(query)}"

    def cdn_url(
        self,
        key: str,
        storage_name: str = "default",
        ttl: int | None = None,
        query: Mapping[str, Any] | None = None,
    ) -> str:
        if not key:
            return ""
        storage = self.get_storage(storage_name)
        if not storage.cdn_base_url:
            raise ValueError("cdn_base_url is required when calling cdn_url")
        path = self._signed_path(storage, key, ttl)
        return self._with_query(self._join_url(storage.cdn_base_url, path), query)

    def cdn_proxy_url(
        self,
        key: str,
        storage_name: str = "default",
        ttl: int | None = None,
        query: Mapping[str, Any] | None = None,
    ) -> str:
        if not key:
            return ""
        storage = self.get_storage(storage_name)
        # Preserve unob's current precedence: global proxy first, then storage.
        proxy_base_url = self.cdn_proxy_base_url or storage.cdn_proxy_base_url
        if not proxy_base_url:
            raise ValueError(
                "cdn_proxy_base_url is required when calling cdn_proxy_url"
            )
        signed_path = self._signed_path(storage, key, ttl)
        path = f"{storage_name}/{signed_path.lstrip('/')}"
        return self._with_query(self._join_url(proxy_base_url, path), query)

    def cdn_download_url(
        self,
        key: str,
        storage_name: str = "default",
        ttl: int | None = None,
        query: Mapping[str, Any] | None = None,
    ) -> str:
        storage = self.get_storage(storage_name)
        if storage.cdn_proxy_base_url or self.cdn_proxy_base_url:
            return self.cdn_proxy_url(key, storage_name, ttl, query)
        return self.cdn_url(key, storage_name, ttl, query)

    @staticmethod
    def _is_not_found(exc: httpx.HTTPError) -> bool:
        return (
            isinstance(exc, httpx.HTTPStatusError)
            and exc.response.status_code == 404
        )

    def _read_via_cdn(
        self,
        key: str,
        storage_name: str,
        ttl: int | None,
        query: Mapping[str, Any] | None,
    ) -> bytes:
        url = self.cdn_download_url(key, storage_name, ttl, query)
        logger.info("Downloading object via CDN: storage=%s key=%s", storage_name, key)
        try:
            response = self._client.get(url)
            response.raise_for_status()
            return response.content
        except httpx.HTTPError as exc:
            if self._is_not_found(exc):
                raise
            logger.warning(
                "CDN download failed, falling back to OSS: storage=%s key=%s",
                storage_name,
                key,
                exc_info=True,
            )
            return self.get_bucket(storage_name, internal=False).get_object(key).read()

    def read_object(
        self,
        key: str,
        storage_name: str = "default",
        ttl: int | None = None,
        query: Mapping[str, Any] | None = None,
    ) -> bytes:
        if not self.use_internal_endpoint and self.prefer_cdn:
            return self._read_via_cdn(key, storage_name, ttl, query)
        logger.info(
            "Downloading object via OSS SDK: storage=%s key=%s internal_endpoint=%s",
            storage_name,
            key,
            self.use_internal_endpoint,
        )
        return self.get_bucket(storage_name).get_object(key).read()

    # More explicit alias for new callers; read_object preserves unob terminology.
    read_bytes = read_object

    def _read_via_cdn_to_file(
        self,
        key: str,
        path: Path,
        storage_name: str,
        ttl: int | None,
        query: Mapping[str, Any] | None,
    ) -> Path:
        url = self.cdn_download_url(key, storage_name, ttl, query)
        temporary_path = path.with_name(f".{path.name}.{os.getpid()}.download")
        logger.info(
            "Downloading object via CDN to file: storage=%s key=%s path=%s",
            storage_name,
            key,
            path,
        )
        try:
            with self._client.stream("GET", url) as response:
                response.raise_for_status()
                with temporary_path.open("wb") as file:
                    for chunk in response.iter_bytes():
                        file.write(chunk)
            temporary_path.replace(path)
            return path
        except httpx.HTTPError as exc:
            temporary_path.unlink(missing_ok=True)
            if self._is_not_found(exc):
                raise
            logger.warning(
                "CDN file download failed, falling back to OSS: storage=%s key=%s",
                storage_name,
                key,
                exc_info=True,
            )
            self.get_bucket(storage_name, internal=False).get_object_to_file(
                key, filename=path
            )
            return path
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise

    def read_object_to_file(
        self,
        key: str,
        filepath: str | os.PathLike[str],
        storage_name: str = "default",
        ttl: int | None = None,
        query: Mapping[str, Any] | None = None,
    ) -> Path:
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not self.use_internal_endpoint and self.prefer_cdn:
            return self._read_via_cdn_to_file(
                key, path, storage_name, ttl, query
            )
        logger.info(
            "Downloading object via OSS SDK to file: storage=%s key=%s path=%s "
            "internal_endpoint=%s",
            storage_name,
            key,
            path,
            self.use_internal_endpoint,
        )
        self.get_bucket(storage_name).get_object_to_file(key, filename=path)
        return path

    # More explicit alias for new callers.
    download_file = read_object_to_file
