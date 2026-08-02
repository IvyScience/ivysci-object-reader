import datetime as dt

from ivysci_object_reader import auth_b


def test_auth_b_matches_unob_vectors():
    expires_at = dt.datetime(2020, 8, 6, 17, 37)
    cases = [
        (
            "document/26/b61519d0-0ea6-47f5-898f-772240390f5f.pdf",
            "311a4656a42c14608a65321d25f435d5",
        ),
        (
            "/document/26/b61519d0-0ea6-47f5-898f-772240390f5f.pdf",
            "311a4656a42c14608a65321d25f435d5",
        ),
        ("/测试.pdf", "8e3a8002b71244269e221f23d01ea3a2"),
    ]

    for path, expected_digest in cases:
        signed = auth_b("12345", path, expires_at)
        timestamp, digest, _ = signed.split("/", maxsplit=2)
        assert timestamp == "202008061737"
        assert digest == expected_digest
