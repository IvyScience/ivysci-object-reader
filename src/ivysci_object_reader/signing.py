"""CDN URL signing helpers."""

from __future__ import annotations

import datetime as dt
import hashlib
from urllib.parse import quote, urljoin


def auth_b(auth_key: str, path: str, expires_at: dt.datetime) -> str:
    """Create the Type-B signed path used by the ivySCI CDN.

    ``expires_at`` must already be expressed in the timezone expected by the
    CDN. The reader defaults to ``Asia/Shanghai`` to preserve unob's behavior.
    """

    normalized_path = urljoin("/", quote(path))
    expires = expires_at.strftime("%Y%m%d%H%M")
    digest = hashlib.md5(
        f"{auth_key}{expires}{normalized_path}".encode("utf8")
    ).hexdigest()
    return f"{expires}/{digest}{normalized_path}"
