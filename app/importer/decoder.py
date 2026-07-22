from __future__ import annotations

import io
import re
import unicodedata
from pathlib import Path

import fitz
from fontTools.ttLib import TTFont

_DIGIT_RUN_RE = re.compile(r"\d+")
_DECIMAL_RE = re.compile(r"\d+[.,]\d+")

_CANON_TRANS = str.maketrans({"ھ": "ه", "ی": "ي", "ک": "ك", "ے": "ى"})

# A few glyphs are absent/ambiguous in the cmap of the result template.
# They are inferred from the standard Arabic glyph sequence used by the embedded font.
_INFERRED_GLYPHS: dict[int, str] = {
    895: "ء",
    897: "آ",
    898: "آ",
    899: "أ",
    905: "ئ",
    906: "ئ",
    925: "ج",
    926: "ج",
    933: "خ",
    934: "خ",
    949: "ش",
    957: "ض",
    973: "غ",
    974: "غ",
    1007: "ى",
    1013: "لآ",
}


def _canonical_arabic(value: str) -> str:
    return unicodedata.normalize("NFKC", value).translate(_CANON_TRANS)


def _mapping_from_font_bytes(content: bytes) -> dict[int, str]:
    font = TTFont(io.BytesIO(content), lazy=True)
    order = font.getGlyphOrder()
    reverse: dict[int, set[int]] = {}
    for table in font["cmap"].tables:
        if table.isUnicode():
            for codepoint, glyph_name in table.cmap.items():
                try:
                    gid = order.index(glyph_name)
                except ValueError:
                    continue
                reverse.setdefault(gid, set()).add(codepoint)

    mapping: dict[int, str] = {}
    for gid, codepoints in reverse.items():
        choices: list[str] = []
        for codepoint in sorted(codepoints):
            text = _canonical_arabic(chr(codepoint))
            if text and any("\u0600" <= char <= "\u06ff" for char in text):
                choices.append(text)
        if choices:
            mapping[gid] = sorted(set(choices), key=lambda item: (len(item), item))[0]

    mapping.update(_INFERRED_GLYPHS)
    for gid in (1001, 1002, 1003, 1004):
        mapping[gid] = "ه"
    for gid in (1009, 1010, 1011):
        mapping[gid] = "ي"
    return mapping


def extract_best_mapping(pdf_path: Path) -> dict[int, str]:
    """Extract the embedded font with the largest Arabic cmap from a PDF."""
    best: dict[int, str] = {}
    with fitz.open(pdf_path) as document:
        seen: set[int] = set()
        for page in document:
            for font_info in page.get_fonts(full=True):
                xref = int(font_info[0])
                if xref <= 0 or xref in seen:
                    continue
                seen.add(xref)
                try:
                    extracted = document.extract_font(xref)
                    content = extracted[-1]
                    if not isinstance(content, (bytes, bytearray)) or not content:
                        continue
                    mapping = _mapping_from_font_bytes(bytes(content))
                    if len(mapping) > len(best):
                        best = mapping
                except Exception:
                    continue
            if len(best) >= 80:
                break
    if not best:
        raise RuntimeError("لم أتمكن من استخراج خط عربي قابل للفك من ملف PDF")
    return best


def text_needs_custom_decode(text: str) -> bool:
    arabic = sum(1 for char in text if "\u0600" <= char <= "\u06ff")
    suspicious = sum(
        1
        for char in text
        if "\u0370" <= char <= "\u03ff" or 0x0380 <= ord(char) <= 1100
    )
    return suspicious > max(20, arabic * 2)


def _repair_reversed_numbers(line: str) -> str:
    # After reversing a visual RTL line, integer runs need per-run reversal,
    # while decimal values (for example averages) need the complete token reversed.
    protected: list[str] = []

    def protect_decimal(match: re.Match[str]) -> str:
        marker = f"@@DEC{len(protected)}@@"
        protected.append(match.group(0)[::-1])
        return marker

    line = _DECIMAL_RE.sub(protect_decimal, line)
    line = _DIGIT_RUN_RE.sub(lambda match: match.group(0)[::-1], line)
    for index, value in enumerate(protected):
        line = line.replace(f"@@DEC{index}@@", value)
    return line


def decode_visual_line(line: str, mapping: dict[int, str]) -> str:
    output: list[str] = []
    for char in line[::-1]:
        codepoint = ord(char)
        if char in {"\x03", "\x10", "\x12"}:
            output.append(" ")
        elif codepoint in mapping:
            output.append(mapping[codepoint])
        else:
            output.append(char)
    return _repair_reversed_numbers("".join(output))


def decode_pdf_text(raw_text: str, mapping: dict[int, str] | None) -> str:
    if not text_needs_custom_decode(raw_text):
        return raw_text
    if not mapping:
        raise RuntimeError("النص يحتاج فك ترميز لكن خريطة الخط غير متوفرة")
    return "\n".join(decode_visual_line(line, mapping) for line in raw_text.split("\n"))
