# ivysci-object-reader

A framework-independent Aliyun OSS object reader with configurable CDN routing
and OSS fallback.

- use the internal OSS endpoint for workloads running inside an Aliyun VPC;
- otherwise use a private-network CDN proxy when configured, or a public CDN;
- fall back from CDN network/HTTP errors to the public OSS endpoint;
- treat CDN `404` as authoritative and do not fall back;
- write file downloads atomically so an interrupted response cannot leave a
  partial destination file.

The package does not read framework settings, YAML files, or environment
variables. The host application loads its configuration and injects it.

## Install

Install a tagged release directly from the public GitHub repository:

```bash
python -m pip install \
  "ivysci-object-reader @ git+https://github.com/IvyScience/ivysci-object-reader.git@v0.1.1"
```

Poetry:

```toml
[tool.poetry.dependencies]
ivysci-object-reader = { git = "https://github.com/IvyScience/ivysci-object-reader.git", tag = "v0.1.1" }
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
        access_key_id=application_config.oss_access_key_id,
        access_key_secret=application_config.oss_access_key_secret,
    ),
    storages={
        "documents": StorageConfig(
            bucket_name="example-documents-bucket",
            region="cn-shanghai",
            cdn_base_url="https://cdn.example.com/",
            cdn_auth_key=application_config.cdn_auth_key,
            cdn_url_ttl=3600,
        ),
        "assets": StorageConfig(
            bucket_name="example-assets-bucket",
            region="cn-shanghai",
            cdn_base_url="https://assets.example.com/",
        ),
    },
    cdn_proxy_base_url="http://cache.internal.example/",
    use_internal_endpoint=application_config.use_internal_oss,
    prefer_cdn=application_config.prefer_cdn,
)

content = reader.read_object("fixtures/example-document.pdf", "documents")
reader.read_object_to_file(
    "fixtures/example-document.pdf",
    "/tmp/example-document.pdf",
    "documents",
)
reader.close()
```

New callers may use the equivalent names `read_bytes()` and `download_file()`.

## Configuration

Configuration remains owned by the host project. Convert the values loaded by
your preferred settings system into `AliyunCredentials` and `StorageConfig`,
then pass them to `ObjectReader`.

Never commit credentials or CDN signing keys to an application repository.

## Development

```bash
python -m pip install -e ".[test]"
python -m pip install build
python -m pytest
python -m build
```

## License

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE).
