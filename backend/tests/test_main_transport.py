import pytest

from main import _validate_production_transport


def test_render_private_redis_host_is_allowed(monkeypatch):
    monkeypatch.setattr("main.settings.ENVIRONMENT", "production")
    monkeypatch.setattr(
        "main.settings.REDIS_URL", "redis://red-dc4qe4jl550s73ab4710:6379"
    )

    _validate_production_transport()


def test_public_plaintext_redis_is_rejected(monkeypatch):
    monkeypatch.setattr("main.settings.ENVIRONMENT", "production")
    monkeypatch.setattr("main.settings.REDIS_URL", "redis://cache.example.com:6379")

    with pytest.raises(RuntimeError, match="must use TLS"):
        _validate_production_transport()
