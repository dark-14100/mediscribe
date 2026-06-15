"""Multilingual: language registry + generator instruction (A) + cross-lingual (B)."""
from core.languages import (
    DEFAULT_LANGUAGE,
    canonical_language,
    is_cross_lingual,
    is_default_language,
    language_label,
    month_names,
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


# --- Phase B: cross-lingual detection + localized data ---------------------


def test_normalize_accepts_whisper_language_names():
    # Whisper's verbose_json reports detected language as an English name.
    assert normalize_language("Spanish") == "es"
    assert normalize_language("french") == "fr"


def test_canonical_language_preserves_unsupported():
    # normalize_language collapses unknown -> en (note language must be supported);
    # canonical_language keeps a real-but-unsupported detected language.
    assert normalize_language("ja") == "en"
    assert canonical_language("ja") == "ja"
    assert canonical_language("Spanish") == "es"
    assert canonical_language("") is None


def test_is_cross_lingual():
    assert is_cross_lingual("en", "es") is True
    assert is_cross_lingual("es", "es") is False
    # Unknown side -> assume same-language (safe default).
    assert is_cross_lingual("en", None) is False
    assert is_cross_lingual(None, "es") is False
    # English name vs code still resolves to equal.
    assert is_cross_lingual("en", "English") is False


def test_month_names():
    assert "enero" in month_names("es")
    assert "janvier" in month_names("fr")
    assert month_names("en") == []  # English handled by the base de-id pattern


def test_section_labels_localized_and_fallback():
    from core.note_templates import section_labels

    en = section_labels("soap")
    assert en["assessment"] == "Assessment"
    es = section_labels("soap", "es")
    assert es["assessment"] == "Evaluación"
    # Unsupported language falls back to English labels.
    assert section_labels("soap", "ja")["assessment"] == "Assessment"
