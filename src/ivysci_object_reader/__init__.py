"""Public API for ivysci-object-reader."""

from .config import AliyunCredentials, StorageConfig
from .reader import ObjectReader
from .signing import auth_b

__all__ = [
    "AliyunCredentials",
    "ObjectReader",
    "StorageConfig",
    "auth_b",
]

__version__ = "0.1.0"
