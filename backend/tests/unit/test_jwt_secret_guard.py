"""BE-31 step 2: production refuses to start on the public fallback JWT secret."""

import pytest

from mesiri.domains.identity import auth_service


def test_production_refuses_the_default_secret(monkeypatch):
    monkeypatch.setattr(auth_service, "SECRET_KEY", auth_service._DEFAULT_SECRET)
    with pytest.raises(RuntimeError, match="MESIRI_JWT_SECRET"):
        auth_service.check_jwt_secret("production")
    with pytest.raises(RuntimeError):
        auth_service.check_jwt_secret(" Production ")


@pytest.mark.parametrize("environment", [None, "", "test", "development", "staging"])
def test_other_environments_only_warn(monkeypatch, environment):
    monkeypatch.setattr(auth_service, "SECRET_KEY", auth_service._DEFAULT_SECRET)
    auth_service.check_jwt_secret(environment)


def test_production_with_a_real_secret_starts(monkeypatch):
    monkeypatch.setattr(auth_service, "SECRET_KEY", "x" * 64)
    auth_service.check_jwt_secret("production")
