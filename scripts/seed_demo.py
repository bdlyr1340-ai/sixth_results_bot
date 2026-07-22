from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from app.database import Database
from app.models import StudentRecord
from app.text_utils import normalize_arabic


async def seed(database_path: Path) -> None:
    db = Database(database_path)
    await db.init()
    import_id = await db.create_import(
        province="البصرة",
        branch="علمي",
        year="2025/2026",
        exam_round="الأول",
        archive_name="demo.zip",
        archive_path="demo.zip",
        replace_existing=False,
    )
    names = [
        ("غدير ميثاق ابراهيم عبدالشهيد", "162612520110068"),
        ("نبأ ليث جاسم احمد", "1626125207200212"),
        ("رؤى حازم عادل باقر", "162612321950019"),
    ]
    records = [
        StudentRecord(
            province="البصرة",
            branch="علمي",
            year="2025/2026",
            exam_round="الأول",
            directorate="البصرة",
            school_code="DEMO",
            school_name="مدرسة تجريبية - بيانات غير حقيقية",
            exam_number=exam,
            full_name=name,
            normalized_name=normalize_arabic(name),
            islamic="80",
            arabic="75",
            english="70",
            biology="85",
            mathematics="65",
            chemistry="77",
            physics="73",
            result="ناجح",
            total="525",
            average="75.00",
            source_file="demo.pdf",
            source_page=1,
            import_id=import_id,
        )
        for name, exam in names
    ]
    await db.replace_scope_and_insert(import_id, records, replace_existing=False)
    await db.update_import(import_id, status="completed", student_count=len(records))
    print(f"Seeded {len(records)} demo records into {database_path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=Path("data/results.sqlite3"))
    args = parser.parse_args()
    args.database.parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(seed(args.database))


if __name__ == "__main__":
    main()
