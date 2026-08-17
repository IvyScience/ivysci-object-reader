import pytest

from ivysci_object_reader import AliyunCredentials, StorageConfig


def test_credentials_are_not_in_repr():
    credentials = AliyunCredentials("access-id", "access-secret")

    assert "access-id" not in repr(credentials)
    assert "access-secret" not in repr(credentials)


def test_cdn_auth_requires_ttl():
    with pytest.raises(ValueError, match="cdn_url_ttl"):
        StorageConfig(bucket_name="bucket", cdn_auth_key="secret")


def test_aliyun_endpoints_are_computed_from_region():
    storage = StorageConfig(bucket_name="bucket", region="cn-hangzhou")

    assert storage.endpoint == "oss-cn-hangzhou.aliyuncs.com"
    assert storage.internal_endpoint == "oss-cn-hangzhou-internal.aliyuncs.com"
