"""Unit tests for `doda.ai.data_classification.classify_outbound_content`
— NFR-DATA-001b/c. Pure function, no DB needed; the end-to-end wiring
(blocking C4, recording the classification on `ai.gateway_call.v1`) is
covered by `tests/integration/test_conversations_api.py`.
"""

from doda.ai.data_classification import DataClassification, classify_outbound_content


def test_plain_conversational_text_defaults_to_c2_internal() -> None:
    assert classify_outbound_content("Ertaga uchrashuvni qachon rejalashtiramiz?") == (
        DataClassification.C2_INTERNAL
    )


def test_an_email_address_is_c3_personal() -> None:
    assert classify_outbound_content("Mening kontaktim: ali@example.com") == DataClassification.C3_PERSONAL


def test_an_uzbek_style_phone_number_is_c3_personal() -> None:
    assert classify_outbound_content("Menga qo'ng'iroq qiling: +998901234567") == (
        DataClassification.C3_PERSONAL
    )


def test_a_luhn_valid_card_number_is_c4_sensitive() -> None:
    # A well-known Visa test number — passes the Luhn checksum but is not
    # a real credential.
    assert classify_outbound_content("Kartam raqami: 4111111111111111") == DataClassification.C4_SENSITIVE


def test_a_luhn_invalid_digit_sequence_is_not_misclassified_as_a_card_number() -> None:
    # Same length as a real card number, but fails the Luhn checksum — an
    # order number or ID, not a card. Falls through to the default C2.
    assert classify_outbound_content("Buyurtma raqami: 1234567890123456") == DataClassification.C2_INTERNAL


def test_an_iban_looking_string_is_c4_sensitive() -> None:
    assert classify_outbound_content("Hisob raqami: DE89370400440532013000") == (
        DataClassification.C4_SENSITIVE
    )


def test_a_health_keyword_is_c4_sensitive() -> None:
    assert classify_outbound_content("Bemorning diagnozi bilan tanishtiring") == (
        DataClassification.C4_SENSITIVE
    )


def test_a_legal_keyword_is_c4_sensitive() -> None:
    assert classify_outbound_content("Bu jinoyat ishi bo'yicha maslahat kerak") == (
        DataClassification.C4_SENSITIVE
    )


def test_content_matching_both_c4_and_c3_patterns_is_classified_as_the_higher_c4() -> None:
    # A card number next to an email must never be under-classified as C3
    # just because the C3 pattern happens to match too.
    assert classify_outbound_content("Kartam 4111111111111111, emailim ali@example.com") == (
        DataClassification.C4_SENSITIVE
    )


def test_generic_mentions_of_a_hospital_are_not_treated_as_c4_by_themselves() -> None:
    # Module docstring's own stated limitation: naming a place is not the
    # same as disclosing someone's own health data — deliberately narrow,
    # same bar outbound_guard applies to secrets.
    assert classify_outbound_content("Ertaga shifoxonaga borishim kerak") == DataClassification.C2_INTERNAL
