import pytest

from asset_scout.security import UnsafeURL, validate_remote_url


def test_url_requires_https_and_allowlist(monkeypatch):
    monkeypatch.setattr("asset_scout.security.socket.getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 443))])
    assert validate_remote_url("https://upload.wikimedia.org/file.jpg", {"upload.wikimedia.org"})
    with pytest.raises(UnsafeURL):
        validate_remote_url("http://upload.wikimedia.org/file.jpg", {"upload.wikimedia.org"})
    with pytest.raises(UnsafeURL):
        validate_remote_url("https://example.com/file.jpg", {"upload.wikimedia.org"})


def test_empty_allowlist_rejects_every_host(monkeypatch):
    monkeypatch.setattr(
        "asset_scout.security.socket.getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 443))],
    )
    with pytest.raises(UnsafeURL, match="provider allowlist"):
        validate_remote_url("https://example.com/file.jpg", set())


def test_private_ip_is_rejected():
    with pytest.raises(UnsafeURL):
        validate_remote_url("https://127.0.0.1/file", {"127.0.0.1"})
