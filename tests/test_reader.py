from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from ivysci_object_reader import AliyunCredentials, ObjectReader, StorageConfig


@pytest.fixture
def storage():
    return StorageConfig(
        bucket_name="example-documents-bucket",
        cdn_base_url="https://cdn.example.com/",
        cdn_auth_key="test-cdn-signing-key",
        cdn_url_ttl=3600,
    )


def make_reader(storage, **kwargs):
    return ObjectReader(
        credentials=AliyunCredentials("test-access-key", "test-access-secret"),
        storages={"default": storage},
        **kwargs,
    )


def test_cdn_download_url_prefers_internal_proxy(storage):
    reader = make_reader(
        storage, cdn_proxy_base_url="http://cache.internal.example/"
    )

    url = reader.cdn_download_url("fixtures/example-document.pdf")

    assert url.startswith(
        "http://cache.internal.example/example-documents-bucket/"
    )
    assert url.endswith("/fixtures/example-document.pdf")
    reader.close()


def test_cdn_proxy_url_uses_bucket_name_not_storage_name():
    storage = StorageConfig(
        bucket_name="ivypri-testing",
        cdn_base_url="https://private-testing.cdn.ivysci.com/",
        cdn_auth_key="test-cdn-signing-key",
        cdn_url_ttl=3600,
    )
    reader = make_reader(
        storage, cdn_proxy_base_url="http://cache.internal.example/"
    )

    url = reader.cdn_download_url("fixtures/example-document.pdf")

    assert url.startswith("http://cache.internal.example/ivypri-testing/")
    assert "/default/" not in url
    reader.close()


def test_cdn_download_url_uses_public_cdn_without_proxy(storage):
    reader = make_reader(storage)

    url = reader.cdn_download_url("fixtures/example-document.pdf")

    assert url.startswith("https://cdn.example.com/")
    assert url.endswith("/fixtures/example-document.pdf")
    reader.close()


def test_cdn_url_preserves_query(storage):
    reader = make_reader(storage)

    url = reader.cdn_url(
        "fixtures/example-document.pdf",
        query={"download": "1", "name": "example file"},
    )

    assert url.endswith(
        "/fixtures/example-document.pdf?download=1&name=example+file"
    )
    reader.close()


def test_read_object_uses_internal_oss_when_enabled(storage):
    bucket = MagicMock()
    bucket.get_object.return_value.read.return_value = b"internal-oss"
    bucket_factory = MagicMock(return_value=bucket)
    http_client = MagicMock()
    reader = make_reader(
        storage,
        use_internal_endpoint=True,
        http_client=http_client,
        bucket_factory=bucket_factory,
    )

    assert reader.read_object("fixtures/example-document.pdf") == b"internal-oss"
    bucket_factory.assert_called_once_with(storage, True)
    http_client.get.assert_not_called()


def test_read_object_uses_public_oss_when_cdn_is_not_preferred(storage):
    bucket = MagicMock()
    bucket.get_object.return_value.read.return_value = b"public-oss"
    bucket_factory = MagicMock(return_value=bucket)
    http_client = MagicMock()
    reader = make_reader(
        storage,
        prefer_cdn=False,
        http_client=http_client,
        bucket_factory=bucket_factory,
    )

    assert reader.read_object("fixtures/example-document.pdf") == b"public-oss"
    bucket_factory.assert_called_once_with(storage, False)
    http_client.get.assert_not_called()


def test_read_object_uses_cdn(storage):
    response = MagicMock(content=b"cdn")
    response.raise_for_status.return_value = None
    http_client = MagicMock()
    http_client.get.return_value = response
    bucket_factory = MagicMock()
    reader = make_reader(
        storage,
        http_client=http_client,
        bucket_factory=bucket_factory,
    )

    assert reader.read_object("fixtures/example-document.pdf") == b"cdn"
    bucket_factory.assert_not_called()


def test_read_object_falls_back_to_public_oss_on_cdn_500(storage):
    request = httpx.Request("GET", "https://cdn.example.com/example-document.pdf")
    response = httpx.Response(500, request=request)
    http_client = MagicMock()
    http_client.get.return_value = response
    bucket = MagicMock()
    bucket.get_object.return_value.read.return_value = b"oss"
    bucket_factory = MagicMock(return_value=bucket)
    reader = make_reader(
        storage,
        cdn_proxy_base_url="http://cache.internal.example/",
        http_client=http_client,
        bucket_factory=bucket_factory,
    )

    assert reader.read_object("fixtures/example-document.pdf") == b"oss"
    bucket_factory.assert_called_once_with(storage, False)


def test_read_object_does_not_fallback_on_cdn_404(storage):
    request = httpx.Request("GET", "https://cdn.example.com/example-document.pdf")
    response = httpx.Response(404, request=request)
    http_client = MagicMock()
    http_client.get.return_value = response
    bucket_factory = MagicMock()
    reader = make_reader(
        storage,
        http_client=http_client,
        bucket_factory=bucket_factory,
    )

    with pytest.raises(httpx.HTTPStatusError):
        reader.read_object("fixtures/example-document.pdf")

    bucket_factory.assert_not_called()


def test_read_object_falls_back_on_network_error(storage):
    request = httpx.Request("GET", "https://cdn.example.com/example-document.pdf")
    http_client = MagicMock()
    http_client.get.side_effect = httpx.ConnectError("failed", request=request)
    bucket = MagicMock()
    bucket.get_object.return_value.read.return_value = b"oss"
    bucket_factory = MagicMock(return_value=bucket)
    reader = make_reader(
        storage,
        http_client=http_client,
        bucket_factory=bucket_factory,
    )

    assert reader.read_object("fixtures/example-document.pdf") == b"oss"


def test_read_object_to_file_is_atomic_and_falls_back(storage, tmp_path):
    request = httpx.Request("GET", "https://cdn.example.com/example-document.pdf")
    response = MagicMock()

    def interrupted_stream():
        yield b"partial"
        raise httpx.ReadError("interrupted", request=request)

    response.raise_for_status.return_value = None
    response.iter_bytes.side_effect = interrupted_stream
    stream_context = MagicMock()
    stream_context.__enter__.return_value = response
    http_client = MagicMock()
    http_client.stream.return_value = stream_context
    bucket = MagicMock()

    def get_object_to_file(key, filename):
        Path(filename).write_bytes(b"complete-from-oss")

    bucket.get_object_to_file.side_effect = get_object_to_file
    reader = make_reader(
        storage,
        http_client=http_client,
        bucket_factory=MagicMock(return_value=bucket),
    )
    destination = tmp_path / "example-document.pdf"

    assert (
        reader.read_object_to_file("fixtures/example-document.pdf", destination)
        == destination
    )
    assert destination.read_bytes() == b"complete-from-oss"
    assert not list(tmp_path.glob(".example-document.pdf.*.download"))


def test_unknown_storage_has_clear_error(storage):
    reader = make_reader(storage)

    with pytest.raises(KeyError, match="unknown storage"):
        reader.get_storage("missing")

    reader.close()
