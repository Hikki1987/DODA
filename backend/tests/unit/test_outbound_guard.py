"""Pure, DB-free tests for `doda.ai.outbound_guard` — the OD-003 pattern
scan. Real-shaped examples (an actual OpenAI test key format, a real PEM
header, a real AWS access-key-id shape), not just "contains the substring
sk-", so a change that narrows the regex too far would be caught."""

from doda.ai.outbound_guard import detect_likely_secret


def test_a_plain_message_is_not_flagged() -> None:
    assert detect_likely_secret("Salom, bugungi ish rejasini tuzib bering.") is None


def test_a_short_word_that_merely_starts_with_sk_dash_is_not_flagged() -> None:
    # Guards against a regex so loose it flags ordinary text — "sk-" alone,
    # or a short non-credential-shaped token after it, must not match.
    assert detect_likely_secret("mening ismim sk-lavlar emas") is None


def test_an_openai_shaped_key_is_flagged() -> None:
    assert (
        detect_likely_secret("mana mening kalitim: sk-abcdefghijklmnopqrstuvwxyz0123456789ABCD")
        == "openai_api_key"
    )


def test_an_anthropic_shaped_key_is_flagged() -> None:
    assert detect_likely_secret("sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789") == "anthropic_api_key"


def test_an_aws_access_key_id_is_flagged() -> None:
    assert detect_likely_secret("AKIAABCDEFGHIJKLMNOP shu kalit") == "aws_access_key_id"


def test_a_google_api_key_is_flagged() -> None:
    assert detect_likely_secret("AIzaSyA1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8") == "google_api_key"


def test_a_github_token_is_flagged() -> None:
    assert detect_likely_secret("ghp_abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQ") == "github_token"


def test_a_slack_token_is_flagged() -> None:
    # Not a digit-run team/bot-id shape (unlike a real Slack token) —
    # GitHub's own push-protection secret scanner flagged an earlier,
    # more realistic-looking version of this fixture as a live Slack
    # token. This shape still matches our own (deliberately loose)
    # pattern without looking like a real credential to a scanner.
    assert detect_likely_secret("xoxb-notarealtoken-fixtureonly") == "slack_token"


def test_a_private_key_block_is_flagged() -> None:
    content = "quyidagi kalitni saqlab qo'y:\n-----BEGIN RSA PRIVATE KEY-----\nMIIB...\n"
    assert detect_likely_secret(content) == "private_key_block"


def test_a_jwt_is_flagged() -> None:
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
    assert detect_likely_secret(f"session tokenim: {jwt}") == "jwt"


def test_a_bearer_header_value_is_flagged() -> None:
    assert (
        detect_likely_secret("Authorization: Bearer abcdefghijklmnopqrstuvwxyz0123456789") == "bearer_token"
    )


def test_the_word_password_alone_is_not_flagged() -> None:
    # Deliberately out of scope — see the module docstring: a generic
    # "password=..." pattern would flag ordinary chat text far more
    # often than it would catch anything real.
    assert detect_likely_secret("parolimni unutib qo'ydim, nima qilishim kerak?") is None
