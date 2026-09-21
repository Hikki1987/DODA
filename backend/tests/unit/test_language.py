"""Pure, DB-free tests for doda.ai.language — FR-CONV-001's detection
heuristic. Real-shaped example sentences in each language/script, not
synthetic keyword soup, so a change that breaks real-world matching
(e.g. losing the apostrophe-normalization) would be caught."""

from doda.ai.language import detect_language, response_language_instruction


def test_uzbek_latin_with_apostrophe_digraph_is_detected() -> None:
    assert detect_language("Bugun ob-havo qanday, tushunarli bo'ldimi?") == "UZ"


def test_uzbek_latin_common_words_without_a_digraph_is_detected() -> None:
    assert detect_language("Salom, bu ish uchun rahmat sizga") == "UZ"


def test_uzbek_cyrillic_is_detected_as_uzbek_not_russian() -> None:
    # ф-ижрочи vs the plain-Russian-looking parts: "қандай" contains the
    # Uzbek-Cyrillic-only "қ", which never appears in standard Russian.
    assert detect_language("Ассалому алайкум, бугун ишларингиз қандай?") == "UZ"


def test_russian_cyrillic_without_any_uzbek_only_letters_is_russian() -> None:
    assert detect_language("Привет, как дела сегодня?") == "RU"


def test_english_common_words_is_detected() -> None:
    assert detect_language("Hello, how are you today? Please help me with this.") == "EN"


def test_a_short_ambiguous_message_returns_none_rather_than_guessing() -> None:
    assert detect_language("ok") is None


def test_digits_only_returns_none() -> None:
    assert detect_language("12345") is None


def test_blank_returns_none() -> None:
    assert detect_language("   ") is None


def test_apostrophe_variants_are_normalized_before_matching() -> None:
    # U+2019 (right single quote) and U+02BB, in place of a plain ASCII
    # apostrophe — both are commonly typed on phone keyboards for the
    # Uzbek "o'"/"g'" sound.
    assert detect_language("bo’ladi albatta") == "UZ"
    assert detect_language("boʻladi albatta") == "UZ"


def test_response_language_instruction_is_empty_when_undetected() -> None:
    assert response_language_instruction(None) == ""


def test_response_language_instruction_names_each_supported_language() -> None:
    assert "o'zbek" in response_language_instruction("UZ")
    assert "rus" in response_language_instruction("RU")
    assert "ingliz" in response_language_instruction("EN")
