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


def normalize_language(code: str | None) -> str:
    """Return a supported BCP-47 code, falling back to the default.

    Accepts region-tagged codes (``pt-BR`` -> ``pt``) by matching the base.
    """
    raw = (code or "").strip().lower()
    if not raw:
        return DEFAULT_LANGUAGE
    if raw in _BY_CODE:
        return raw
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
