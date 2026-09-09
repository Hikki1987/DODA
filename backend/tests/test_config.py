"""NFR-SEC-001's "configuration scan" verification, made concrete: the
comment on Settings.cors_allowed_origins has always said "never '*'", but
until now nothing enforced it — an operator could set
DODA_CORS_ALLOWED_ORIGINS=* and the app would start up fine, silently
combining with CORSMiddleware's allow_credentials=True into a
wildcard-with-credentials misconfiguration. No DB or running app needed:
this is pure Settings construction.
"""

import pytest
from pydantic import ValidationError

from doda.config import Settings


def test_wildcard_cors_origin_is_rejected() -> None:
    with pytest.raises(ValidationError, match="must not contain"):
        Settings(cors_allowed_origins="*")


def test_wildcard_mixed_with_a_real_origin_is_still_rejected() -> None:
    with pytest.raises(ValidationError, match="must not contain"):
        Settings(cors_allowed_origins="http://localhost:3000, *")


def test_a_normal_origin_list_is_accepted() -> None:
    settings = Settings(cors_allowed_origins="http://localhost:3000,https://app.example.com")
    assert settings.cors_allowed_origins == "http://localhost:3000,https://app.example.com"
