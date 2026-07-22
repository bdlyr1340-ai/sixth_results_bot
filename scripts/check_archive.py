from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from app.importer.jobs import _process_archive_sync


def main() -> None:
    parser = argparse.ArgumentParser(description="Dry-run a result ZIP without saving to the database")
    parser.add_argument("archive", type=Path)
    parser.add_argument("--province", required=True)
    parser.add_argument("--branch", default="علمي")
    parser.add_argument("--year", default="2025/2026")
    parser.add_argument("--round", dest="exam_round", default="الأول")
    args = parser.parse_args()

    job = {
        "id": 999999,
        "archive_path": str(args.archive.resolve()),
        "province": args.province,
        "branch": args.branch,
        "year": args.year,
        "exam_round": args.exam_round,
    }

    def progress(processed: int, total: int, students: int, errors: int) -> None:
        print(f"{processed}/{total} PDF | {students} students | {errors} warnings")

    with tempfile.TemporaryDirectory() as directory:
        records, files, errors = _process_archive_sync(job, Path(directory), progress)

    print("\nDone")
    print("PDF files:", files)
    print("Students:", len(records))
    print("Warnings:", len(errors))
    for warning in errors[:20]:
        print("-", warning)
    if records:
        print("First record:", records[0])
        print("Last record:", records[-1])


if __name__ == "__main__":
    main()
