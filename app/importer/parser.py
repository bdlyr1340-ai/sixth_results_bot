from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from app.constants import RESULT_STATUSES
from app.models import StudentRecord
from app.text_utils import clean_text, normalize_arabic

_STATUS_PATTERN = "|".join(re.escape(item) for item in RESULT_STATUSES)
_ROW_HEAD_RE = re.compile(r"^\s*(\d{1,4})\s+(\d{12,20})\s+(.+?)\s*$")
_STATUS_RE = re.compile(rf"\s+({_STATUS_PATTERN})\s+")
_SCORE_RE = re.compile(r"^(?:\d{1,3}%?|صفر|م|غ|غائب|مؤجل|مؤجلة|ثمان|عشر)$")


def _line_value(text: str, labels: Iterable[str]) -> str:
    for line in text.splitlines():
        compact = clean_text(line)
        comparable = compact.replace("ـ", "")
        for label in labels:
            if comparable.startswith(label.replace("ـ", "")) and ":" in compact:
                return clean_text(compact.split(":", 1)[1])
    return ""


def parse_metadata(page_text: str, fallback: dict[str, str]) -> dict[str, str]:
    school_code_match = re.search(r"رمز\s+المدرسة\s*:\s*(\d+)", page_text)
    year_match = re.search(r"20\d{2}\s*/\s*20\d{2}", page_text)
    round_match = re.search(r"الدور\s+([\u0600-\u06FF]+)", page_text)

    directorate = _line_value(page_text, ("المديرية",)) or fallback.get("directorate", "")
    school_name = _line_value(page_text, ("المدرسة", "المدرســــــة")) or fallback.get("school_name", "")
    branch = _line_value(page_text, ("الفرع", "الفـــرع")) or fallback.get("branch", "علمي")

    if school_name:
        school_name = re.sub(r"^\s*[:\-]+", "", school_name).strip()
    if branch:
        branch = re.sub(r"^\s*[:\-]+", "", branch).strip()

    return {
        "directorate": directorate,
        "school_code": school_code_match.group(1) if school_code_match else fallback.get("school_code", ""),
        "school_name": school_name,
        "branch": branch,
        "year": clean_text(year_match.group(0)) if year_match else fallback.get("year", "2025/2026"),
        "exam_round": round_match.group(1) if round_match else fallback.get("exam_round", "الأول"),
    }


def _is_score(token: str) -> bool:
    token = token.strip("،,:؛")
    if not _SCORE_RE.fullmatch(token):
        return False
    if token.rstrip("%").isdigit():
        number = int(token.rstrip("%"))
        return 0 <= number <= 100
    return True


def _normalise_score(token: str) -> str:
    token = token.strip("،,:؛")
    if token == "صفر":
        return "0"
    if token in {"م", "غ", "غائب", "مؤجل", "مؤجلة"}:
        return token
    if token.endswith("%") and token[:-1].isdigit():
        return token
    if token.isdigit():
        return str(int(token))
    return token


def parse_student_line(line: str) -> tuple[dict[str, str], str] | None:
    line = clean_text(line)
    status_match = _STATUS_RE.search(f" {line} ")
    if not status_match:
        return None

    status = status_match.group(1)
    start = max(0, status_match.start() - 1)
    end = max(start, status_match.end() - 1)
    prefix = clean_text(line[:start])
    suffix = clean_text(line[end:])

    head = _ROW_HEAD_RE.match(prefix)
    if not head:
        return None

    sequence, exam_number, remainder = head.groups()
    remaining_tokens = remainder.split()
    scores_reversed: list[str] = []
    while remaining_tokens and _is_score(remaining_tokens[-1]) and len(scores_reversed) < 8:
        scores_reversed.append(_normalise_score(remaining_tokens.pop()))

    if len(scores_reversed) < 7:
        return None

    name = clean_text(" ".join(remaining_tokens))
    if len(name.split()) < 3 or not any("\u0600" <= char <= "\u06ff" for char in name):
        return None

    scores = list(reversed(scores_reversed))
    languages = ""
    if len(scores) >= 8:
        languages = scores[-1]
        scores = scores[:7]
    if len(scores) != 7:
        return None

    suffix_tokens = suffix.split()
    total = suffix_tokens[0] if suffix_tokens else ""
    average = suffix_tokens[1] if len(suffix_tokens) > 1 else ""

    return (
        {
            "sequence": sequence,
            "exam_number": exam_number,
            "full_name": name,
            "islamic": scores[0],
            "arabic": scores[1],
            "english": scores[2],
            "biology": scores[3],
            "mathematics": scores[4],
            "chemistry": scores[5],
            "physics": scores[6],
            "languages": languages,
            "result": status,
            "total": _normalise_score(total) if total else "",
            "average": average,
        },
        sequence,
    )


def parse_decoded_pdf(
    decoded_text: str,
    *,
    province: str,
    branch: str,
    year: str,
    exam_round: str,
    source_file: str,
    import_id: int,
) -> list[StudentRecord]:
    pages = decoded_text.split("\f")
    fallback = {
        "directorate": province,
        "school_code": "",
        "school_name": Path(source_file).stem,
        "branch": branch,
        "year": year,
        "exam_round": exam_round,
    }
    output: list[StudentRecord] = []
    seen_exam_numbers: set[str] = set()

    for page_number, page_text in enumerate(pages, start=1):
        metadata = parse_metadata(page_text, fallback)
        fallback.update(metadata)
        for line in page_text.splitlines():
            parsed = parse_student_line(line)
            if not parsed:
                continue
            row, _ = parsed
            exam_number = row["exam_number"]
            if exam_number in seen_exam_numbers:
                continue
            seen_exam_numbers.add(exam_number)
            output.append(
                StudentRecord(
                    province=province,
                    branch=metadata.get("branch") or branch,
                    year=metadata.get("year") or year,
                    exam_round=metadata.get("exam_round") or exam_round,
                    directorate=metadata.get("directorate") or province,
                    school_code=metadata.get("school_code", ""),
                    school_name=metadata.get("school_name") or Path(source_file).stem,
                    exam_number=exam_number,
                    full_name=row["full_name"],
                    normalized_name=normalize_arabic(row["full_name"]),
                    islamic=row["islamic"],
                    arabic=row["arabic"],
                    english=row["english"],
                    biology=row["biology"],
                    mathematics=row["mathematics"],
                    chemistry=row["chemistry"],
                    physics=row["physics"],
                    languages=row["languages"],
                    result=row["result"],
                    total=row["total"],
                    average=row["average"],
                    source_file=source_file,
                    source_page=page_number,
                    import_id=import_id,
                )
            )
    return output
