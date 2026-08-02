# ivysci-object-reader

Framework-independent Aliyun OSS object reader extracted from `unob`. It keeps
the existing ivySCI runtime behavior:

- use the internal OSS endpoint when the process runs inside the Aliyun VPC;
- otherwise use the internal CDN proxy when configured, or the public CDN;
- fall back from CDN network/HTTP errors to the public OSS endpoint;
- treat CDN `404` as authoritative and do not fall back;
- write file downloads atomically so an interrupted response cannot leave a
  partial destination file.

The package does **not** read Django settings, YAML files, or environment
variables. The host application loads its own configuration and injects it.

## Install

From a private GitHub repository and a release tag:

```bash
python -m pip install \
  "ivysci-object-reader @ git+ssh://git@github.com/IvyScience/ivysci-object-reader.git@v0.1.0"
```

Poetry:

```toml
[tool.poetry.dependencies]
ivysci-object-reader = {
  git = "ssh://git@github.com/IvyScience/ivysci-object-reader.git",
  tag = "v0.1.0"
}
```

## Usage

```python
from ivysci_object_reader import (
    AliyunCredentials,
    ObjectReader,
    StorageConfig,
)

reader = ObjectReader(
    credentials=AliyunCredentials(
        access_key_id=app_settings.aliyun_access_key,
        access_key_secret=app_settings.aliyun_access_secret,
    ),
    storages={
        "default": StorageConfig(
            bucket_name="ivypri",
            region="cn-shanghai",
            cdn_base_url="https://private.cdn.ivysci.com/",
            cdn_auth_key="...",
            cdn_url_ttl=86400,
        ),
        "asset": StorageConfig(
            bucket_name="ivyasset",
            region="cn-shanghai",
            cdn_base_url="https://asset.cdn.ivysci.com/",
        ),
    },
    cdn_proxy_base_url=app_settings.oss_cdn_proxy_base_url,
    use_internal_endpoint=app_settings.oss_use_internal_endpoint,
    prefer_cdn=not app_settings.environment.is_development,
)

content = reader.read_object("document/example.pdf")
reader.read_object_to_file("document/example.pdf", "/tmp/example.pdf")
```

New callers may use the equivalent names `read_bytes()` and `download_file()`.

## Host configuration

Configuration remains owned by the host project. For example, unob may keep
the same `settings.yaml` shape and convert each parsed storage entry into a
`StorageConfig` before creating `ObjectReader`.

No credentials or CDN signing keys should be committed to this repository.

## Development

```bash
python -m pip install -e ".[test]"
python -m pytest
python -m build
```
