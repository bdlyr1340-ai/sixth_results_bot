from app.importer.parser import parse_student_line
from app.text_utils import normalize_arabic, valid_search_name


def test_normalize_arabic_variants() -> None:
    assert normalize_arabic("إبراهيم  عبد الشهيد") == "ابراهيم عبد الشهيد"
    assert normalize_arabic("رؤى حازم عادل") == "روي حازم عادل"


def test_valid_name() -> None:
    assert valid_search_name("غدير ميثاق إبراهيم")
    assert not valid_search_name("غدير ميثاق")


def test_parse_result_row() -> None:
    line = (
        "62 162612520110068 غدير ميثاق ابراهيم عبدالشهيد "
        "96 م 0 82 م 66 0 معيد 0 0"
    )
    parsed = parse_student_line(line)
    assert parsed is not None
    row, sequence = parsed
    assert sequence == "62"
    assert row["full_name"] == "غدير ميثاق ابراهيم عبدالشهيد"
    assert row["islamic"] == "96"
    assert row["chemistry"] == "66"
    assert row["result"] == "معيد"
