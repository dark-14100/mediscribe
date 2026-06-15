"""Supported note languages — single source of truth (mirrored in the frontend).

A curated set of space-delimited-script languages where Whisper ASR + LLaMA
generation are reliable and the lexical grounding gate stays valid. Expand over
time; CJK (which needs word segmentation for grounding) is a later add-on.

Each entry: BCP-47 ``code``, English ``label``, and the language's own
``native_label`` (for the selector). ``en`` is the default and must stay first.
"""
from __future__ import annotations

from typing import Final

DEFAULT_LANGUAGE: Final[str] = "en"

# (code, English label, native label)
SUPPORTED_LANGUAGES: Final[list[dict[str, str]]] = [
    {"code": "en", "label": "English", "native_label": "English"},
    {"code": "es", "label": "Spanish", "native_label": "Español"},
    {"code": "fr", "label": "French", "native_label": "Français"},
    {"code": "de", "label": "German", "native_label": "Deutsch"},
    {"code": "pt", "label": "Portuguese", "native_label": "Português"},
    {"code": "it", "label": "Italian", "native_label": "Italiano"},
    {"code": "nl", "label": "Dutch", "native_label": "Nederlands"},
    {"code": "pl", "label": "Polish", "native_label": "Polski"},
    {"code": "ro", "label": "Romanian", "native_label": "Română"},
    {"code": "sv", "label": "Swedish", "native_label": "Svenska"},
    {"code": "tr", "label": "Turkish", "native_label": "Türkçe"},
    {"code": "id", "label": "Indonesian", "native_label": "Bahasa Indonesia"},
    {"code": "hi", "label": "Hindi", "native_label": "हिन्दी"},
]

_BY_CODE: Final[dict[str, dict[str, str]]] = {
    lang["code"]: lang for lang in SUPPORTED_LANGUAGES
}

# English language names (lowercase) -> code. Whisper's verbose_json reports the
# detected language as an English name (e.g. "spanish"), so we map those back.
_NAME_ALIASES: Final[dict[str, str]] = {
    lang["label"].lower(): lang["code"] for lang in SUPPORTED_LANGUAGES
}


def normalize_language(code: str | None) -> str:
    """Return a supported BCP-47 code, falling back to the default.

    Accepts region-tagged codes (``pt-BR`` -> ``pt``) and English language names
    (``"Spanish"`` -> ``es``, as Whisper reports them).
    """
    raw = (code or "").strip().lower()
    if not raw:
        return DEFAULT_LANGUAGE
    if raw in _BY_CODE:
        return raw
    if raw in _NAME_ALIASES:
        return _NAME_ALIASES[raw]
    base = raw.split("-", 1)[0]
    return base if base in _BY_CODE else DEFAULT_LANGUAGE


def language_label(code: str | None) -> str:
    """English label for a code (for prompts/logging)."""
    return _BY_CODE.get(normalize_language(code), _BY_CODE[DEFAULT_LANGUAGE])["label"]


def native_label(code: str | None) -> str:
    return _BY_CODE.get(normalize_language(code), _BY_CODE[DEFAULT_LANGUAGE])[
        "native_label"
    ]


def is_default_language(code: str | None) -> bool:
    return normalize_language(code) == DEFAULT_LANGUAGE


def canonical_language(code: str | None) -> str | None:
    """Best-effort canonical code that preserves unsupported languages.

    Unlike ``normalize_language`` (which collapses anything unknown to ``en`` for
    the note-output language), this keeps a real-but-unsupported detected language
    as its base token (e.g. ``"ja"``) so cross-lingual detection stays accurate.
    Returns None for empty input.
    """
    raw = (code or "").strip().lower()
    if not raw:
        return None
    if raw in _BY_CODE:
        return raw
    if raw in _NAME_ALIASES:
        return _NAME_ALIASES[raw]
    return raw.split("-", 1)[0] or None


def is_cross_lingual(note_language: str | None, transcript_language: str | None) -> bool:
    """True when the note is written in a different language than was spoken.

    Returns False when either side is unknown (we can't be sure they differ, so
    we keep the safe same-language assumption).
    """
    note = canonical_language(note_language)
    transcript = canonical_language(transcript_language)
    if not note or not transcript:
        return False
    return note != transcript


# --- Gregorian month names per language (for de-identification date stripping) ---
# Months are common-knowledge, low-risk to translate (unlike clinical jargon).
# English is always merged in as a fallback by the de-id layer. Languages absent
# here simply fall back to the English month patterns.
MONTH_NAMES: Final[dict[str, list[str]]] = {
    "es": [
        "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
        "septiembre", "setiembre", "octubre", "noviembre", "diciembre",
        "ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "set",
        "oct", "nov", "dic",
    ],
    "fr": [
        "janvier", "février", "fevrier", "mars", "avril", "mai", "juin",
        "juillet", "août", "aout", "septembre", "octobre", "novembre",
        "décembre", "decembre",
        "janv", "févr", "fevr", "avr", "juil", "sept", "oct", "nov", "déc", "dec",
    ],
    "de": [
        "januar", "februar", "märz", "maerz", "april", "mai", "juni", "juli",
        "august", "september", "oktober", "november", "dezember",
        "jan", "feb", "mär", "maer", "apr", "jun", "jul", "aug", "sep", "okt",
        "nov", "dez",
    ],
    "pt": [
        "janeiro", "fevereiro", "março", "marco", "abril", "maio", "junho",
        "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
        "jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out",
        "nov", "dez",
    ],
    "it": [
        "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
        "agosto", "settembre", "ottobre", "novembre", "dicembre",
        "gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott",
        "nov", "dic",
    ],
    "nl": [
        "januari", "februari", "maart", "april", "mei", "juni", "juli",
        "augustus", "september", "oktober", "november", "december",
        "jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt",
        "nov", "dec",
    ],
    "hi": [
        "जनवरी", "फ़रवरी", "फरवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई",
        "अगस्त", "सितंबर", "अक्तूबर", "अक्टूबर", "नवंबर", "दिसंबर",
    ],
}


def month_names(language: str | None) -> list[str]:
    """Localized month names for a language (empty if none defined)."""
    return list(MONTH_NAMES.get(normalize_language(language), []))
