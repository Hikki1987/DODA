"""Pure-function unit tests for hash_oidc_subject — see
tests/integration/test_identity_service.py for get_or_create_user, which
needs a real DB.
"""

from doda.application.identity_service import hash_oidc_subject


def test_same_provider_and_subject_hash_deterministically() -> None:
    first = hash_oidc_subject(provider="google", subject="1234567890")
    second = hash_oidc_subject(provider="google", subject="1234567890")
    assert first == second


def test_different_subjects_hash_differently() -> None:
    a = hash_oidc_subject(provider="google", subject="1111111111")
    b = hash_oidc_subject(provider="google", subject="2222222222")
    assert a != b


def test_same_subject_on_different_providers_hashes_differently() -> None:
    """The provider prefix matters: two providers issuing the same literal
    subject string must not collide on one User row."""
    google = hash_oidc_subject(provider="google", subject="1234567890")
    other = hash_oidc_subject(provider="other-provider", subject="1234567890")
    assert google != other
