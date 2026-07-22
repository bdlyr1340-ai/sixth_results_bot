from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class StudentRecord:
    province: str
    branch: str
    year: str
    exam_round: str
    directorate: str
    school_code: str
    school_name: str
    exam_number: str
    full_name: str
    normalized_name: str
    islamic: str = ""
    arabic: str = ""
    english: str = ""
    biology: str = ""
    mathematics: str = ""
    chemistry: str = ""
    physics: str = ""
    languages: str = ""
    result: str = ""
    total: str = ""
    average: str = ""
    source_file: str = ""
    source_page: int = 0
    import_id: int = 0
