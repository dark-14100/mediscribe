"""Multilingual Phase A: language registry + generator language instruction."""
from core.languages import (
    DEFAULT_LANGUAGE,
    is_default_language,
    language_label,
    native_label,
    normalize_language,
)


def test_normalize_language_defaults_and_aliases():
    assert normalize_language(None) == "en"
    assert normalize_language("") == "en"
    assert normalize_language("ES") == "es"
    # region-tagged codes fall back to the base language
    assert normalize_language("pt-BR") == "pt"
    # unknown codes fall back to the default
    assert normalize_language("xx") == DEFAULT_LANGUAGE


def test_labels():
    assert language_label("es") == "Spanish"
    assert native_label("es") == "Español"
    assert is_default_language("en") is True
    assert is_default_language("fr") is False


def test_generator_language_instruction_english_is_empty():
    from services.soap_generator import _language_instruction

    # English must be byte-for-byte unchanged -> no extra instruction.
    assert _language_instruction("en") == ""


def test_generator_language_instruction_non_english_mentions_language():
    from services.soap_generator import _language_instruction

    instr = _language_instruction("es")
    assert instr  # non-empty
    assert "Español" in instr
    assert "(es)" in instr
    # JSON keys must stay English.
    assert "keys in English" in instr
