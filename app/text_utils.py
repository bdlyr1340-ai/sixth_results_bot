from __future__ import annotations

import re
import unicodedata

_DIACRITICS_RE = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]")
_NON_ARABIC_RE = re.compile(r"[^\u0600-\u06FF0-9 ]+")
_SPACE_RE = re.compile(r"\s+")

_ARABIC_TRANSLATION = str.maketrans(
    {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ٱ": "ا",
        "ى": "ي",
        "ئ": "ي",
        "ؤ": "و",
        "ة": "ه",
        "ک": "ك",
        "ی": "ي",
        "ھ": "ه",
        "ـ": "",
    }
)


def normalize_arabic(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "")
    value = _DIACRITICS_RE.sub("", value)
    value = value.translate(_ARABIC_TRANSLATION)
    value = _NON_ARABIC_RE.sub(" ", value)
    return _SPACE_RE.sub(" ", value).strip()


def clean_text(value: str) -> str:
    return _SPACE_RE.sub(" ", unicodedata.normalize("NFKC", value or "")).strip()


def valid_search_name(value: str) -> bool:
    tokens = normalize_arabic(value).split()
    return 3 <= len(tokens) <= 6 and all(len(token) >= 2 for token in tokens)
