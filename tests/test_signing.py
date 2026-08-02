import datetime as dt

from ivysci_object_reader import auth_b


def test_auth_b_matches_known_vectors():
    expires_at = dt.datetime(2020, 8, 6, 17, 37)
    cases = [
        (
            "fixtures/example-document.pdf",
            "94c7e07f91613f599481ac52f98b3ad7",
        ),
        (
            "/fixtures/example-document.pdf",
            "94c7e07f91613f599481ac52f98b3ad7",
        ),
        ("/fixtures/示例.pdf", "e615d6c052420d3efd4ee8f555f79b9f"),
    ]

    for path, expected_digest in cases:
        signed = auth_b("test-signing-key", path, expires_at)
        timestamp, digest, _ = signed.split("/", maxsplit=2)
        assert timestamp == "202008061737"
        assert digest == expected_digest
