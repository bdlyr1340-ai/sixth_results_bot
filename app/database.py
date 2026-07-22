from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from rapidfuzz import fuzz

from app.constants import PROVINCES
from app.models import StudentRecord
from app.text_utils import normalize_arabic


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = asyncio.Lock()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    async def init(self) -> None:
        await asyncio.to_thread(self._init_sync)

    def _init_sync(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS imports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    province TEXT NOT NULL,
                    branch TEXT NOT NULL,
                    year TEXT NOT NULL,
                    exam_round TEXT NOT NULL,
                    archive_name TEXT NOT NULL,
                    archive_path TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    replace_existing INTEGER NOT NULL DEFAULT 1,
                    total_files INTEGER NOT NULL DEFAULT 0,
                    processed_files INTEGER NOT NULL DEFAULT 0,
                    student_count INTEGER NOT NULL DEFAULT 0,
                    error_count INTEGER NOT NULL DEFAULT 0,
                    error_log TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT
                );

                CREATE TABLE IF NOT EXISTS students (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    province TEXT NOT NULL,
                    branch TEXT NOT NULL,
                    year TEXT NOT NULL,
                    exam_round TEXT NOT NULL,
                    directorate TEXT NOT NULL DEFAULT '',
                    school_code TEXT NOT NULL DEFAULT '',
                    school_name TEXT NOT NULL DEFAULT '',
                    exam_number TEXT NOT NULL,
                    full_name TEXT NOT NULL,
                    normalized_name TEXT NOT NULL,
                    islamic TEXT NOT NULL DEFAULT '',
                    arabic TEXT NOT NULL DEFAULT '',
                    english TEXT NOT NULL DEFAULT '',
                    biology TEXT NOT NULL DEFAULT '',
                    mathematics TEXT NOT NULL DEFAULT '',
                    chemistry TEXT NOT NULL DEFAULT '',
                    physics TEXT NOT NULL DEFAULT '',
                    languages TEXT NOT NULL DEFAULT '',
                    result TEXT NOT NULL DEFAULT '',
                    total TEXT NOT NULL DEFAULT '',
                    average TEXT NOT NULL DEFAULT '',
                    source_file TEXT NOT NULL DEFAULT '',
                    source_page INTEGER NOT NULL DEFAULT 0,
                    import_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(import_id) REFERENCES imports(id) ON DELETE CASCADE,
                    UNIQUE(province, year, exam_round, branch, exam_number)
                );

                CREATE INDEX IF NOT EXISTS idx_students_search
                    ON students(province, normalized_name);
                CREATE INDEX IF NOT EXISTS idx_students_exam
                    ON students(exam_number);
                CREATE INDEX IF NOT EXISTS idx_students_school
                    ON students(province, school_code);

                CREATE TABLE IF NOT EXISTS users (
                    telegram_id INTEGER PRIMARY KEY,
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL,
                    searches INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS search_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    province TEXT NOT NULL,
                    found INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_search_events_created
                    ON search_events(created_at);
                """
            )

    async def touch_user(self, telegram_id: int, increment_search: bool = False) -> None:
        now = utc_now()

        def operation() -> None:
            with self._connect() as db:
                db.execute(
                    """
                    INSERT INTO users(telegram_id, first_seen, last_seen, searches)
                    VALUES(?, ?, ?, ?)
                    ON CONFLICT(telegram_id) DO UPDATE SET
                        last_seen=excluded.last_seen,
                        searches=users.searches + excluded.searches
                    """,
                    (telegram_id, now, now, 1 if increment_search else 0),
                )

        await asyncio.to_thread(operation)

    async def log_search(self, province: str, found: bool) -> None:
        def operation() -> None:
            with self._connect() as db:
                db.execute(
                    "INSERT INTO search_events(province, found, created_at) VALUES(?, ?, ?)",
                    (province, int(found), utc_now()),
                )

        await asyncio.to_thread(operation)

    async def create_import(
        self,
        *,
        province: str,
        branch: str,
        year: str,
        exam_round: str,
        archive_name: str,
        archive_path: str,
        replace_existing: bool,
    ) -> int:
        def operation() -> int:
            with self._connect() as db:
                cursor = db.execute(
                    """
                    INSERT INTO imports(
                        province, branch, year, exam_round, archive_name, archive_path,
                        status, replace_existing, created_at
                    ) VALUES(?, ?, ?, ?, ?, ?, 'queued', ?, ?)
                    """,
                    (
                        province,
                        branch,
                        year,
                        exam_round,
                        archive_name,
                        archive_path,
                        int(replace_existing),
                        utc_now(),
                    ),
                )
                return int(cursor.lastrowid)

        return await asyncio.to_thread(operation)

    async def update_import(self, import_id: int, **fields: Any) -> None:
        allowed = {
            "status",
            "total_files",
            "processed_files",
            "student_count",
            "error_count",
            "error_log",
            "started_at",
            "finished_at",
        }
        values = {key: value for key, value in fields.items() if key in allowed}
        if not values:
            return

        def operation() -> None:
            assignments = ", ".join(f"{key}=?" for key in values)
            with self._connect() as db:
                db.execute(
                    f"UPDATE imports SET {assignments} WHERE id=?",
                    (*values.values(), import_id),
                )

        await asyncio.to_thread(operation)

    async def get_import(self, import_id: int) -> dict[str, Any] | None:
        def operation() -> dict[str, Any] | None:
            with self._connect() as db:
                row = db.execute("SELECT * FROM imports WHERE id=?", (import_id,)).fetchone()
                return dict(row) if row else None

        return await asyncio.to_thread(operation)

    async def list_imports(self, limit: int = 30) -> list[dict[str, Any]]:
        def operation() -> list[dict[str, Any]]:
            with self._connect() as db:
                rows = db.execute(
                    "SELECT * FROM imports ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
                return [dict(row) for row in rows]

        return await asyncio.to_thread(operation)

    async def pending_import_ids(self) -> list[int]:
        def operation() -> list[int]:
            with self._connect() as db:
                rows = db.execute(
                    "SELECT id FROM imports WHERE status IN ('queued', 'processing') ORDER BY id"
                ).fetchall()
                return [int(row[0]) for row in rows]

        return await asyncio.to_thread(operation)

    async def replace_scope_and_insert(
        self,
        import_id: int,
        records: Sequence[StudentRecord],
        *,
        replace_existing: bool,
    ) -> int:
        if not records:
            return 0
        async with self._write_lock:
            return await asyncio.to_thread(
                self._replace_scope_and_insert_sync,
                import_id,
                records,
                replace_existing,
            )

    def _replace_scope_and_insert_sync(
        self,
        import_id: int,
        records: Sequence[StudentRecord],
        replace_existing: bool,
    ) -> int:
        first = records[0]
        columns = list(asdict(first).keys())
        placeholders = ",".join("?" for _ in columns) + ",?"
        insert_sql = (
            f"INSERT OR REPLACE INTO students({','.join(columns)}, created_at) "
            f"VALUES({placeholders})"
        )
        created_at = utc_now()
        rows = [
            tuple(asdict(record)[column] for column in columns) + (created_at,)
            for record in records
        ]
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if replace_existing:
                db.execute(
                    """
                    DELETE FROM students
                    WHERE province=? AND branch=? AND year=? AND exam_round=?
                    """,
                    (first.province, first.branch, first.year, first.exam_round),
                )
            db.executemany(insert_sql, rows)
        return len(rows)

    async def province_stats(self) -> list[dict[str, Any]]:
        def operation() -> dict[str, dict[str, Any]]:
            with self._connect() as db:
                rows = db.execute(
                    """
                    SELECT province,
                           COUNT(*) AS student_count,
                           COUNT(DISTINCT source_file || ':' || year || ':' || exam_round || ':' || branch) AS file_count,
                           COUNT(DISTINCT school_code || ':' || year || ':' || exam_round || ':' || branch) AS school_count,
                           MAX(created_at) AS updated_at
                    FROM students
                    GROUP BY province
                    """
                ).fetchall()
                return {row["province"]: dict(row) for row in rows}

        found = await asyncio.to_thread(operation)
        return [
            found.get(
                province,
                {
                    "province": province,
                    "student_count": 0,
                    "file_count": 0,
                    "school_count": 0,
                    "updated_at": None,
                },
            )
            for province in PROVINCES
        ]

    async def dashboard_stats(self) -> dict[str, Any]:
        def operation() -> dict[str, Any]:
            with self._connect() as db:
                queries = {
                    "students": "SELECT COUNT(*) FROM students",
                    "files": "SELECT COUNT(DISTINCT source_file || ':' || province || ':' || year || ':' || exam_round || ':' || branch) FROM students",
                    "users": "SELECT COUNT(*) FROM users",
                    "searches": "SELECT COUNT(*) FROM search_events",
                    "found": "SELECT COUNT(*) FROM search_events WHERE found=1",
                    "provinces": "SELECT COUNT(DISTINCT province) FROM students",
                }
                result: dict[str, Any] = {}
                for key, sql in queries.items():
                    row = db.execute(sql).fetchone()
                    result[key] = int(row[0] or 0)
                result["success_rate"] = (
                    round(result["found"] * 100 / result["searches"], 1)
                    if result["searches"]
                    else 0
                )
                return result

        return await asyncio.to_thread(operation)

    async def search_students(
        self, province: str, query: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        normalized = normalize_arabic(query)
        tokens = normalized.split()
        if len(tokens) < 3:
            return []

        def exact_query() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
            with self._connect() as db:
                exact_rows = db.execute(
                    """
                    SELECT * FROM students
                    WHERE province=?
                      AND (normalized_name=? OR normalized_name LIKE ?)
                    ORDER BY CASE WHEN normalized_name=? THEN 0 ELSE 1 END,
                             year DESC, exam_round, full_name
                    LIMIT ?
                    """,
                    (province, normalized, normalized + " %", normalized, limit),
                ).fetchall()
                if exact_rows:
                    return [dict(row) for row in exact_rows], []

                first = tokens[0]
                second = tokens[1]
                candidate_rows = db.execute(
                    """
                    SELECT * FROM students
                    WHERE province=?
                      AND normalized_name LIKE ?
                      AND normalized_name LIKE ?
                    LIMIT 800
                    """,
                    (province, first + " %", "% " + second + "%"),
                ).fetchall()
                return [], [dict(row) for row in candidate_rows]

        exact, candidates = await asyncio.to_thread(exact_query)
        if exact:
            return exact

        scored: list[tuple[float, dict[str, Any]]] = []
        for row in candidates:
            candidate = row["normalized_name"]
            candidate_prefix = " ".join(candidate.split()[: len(tokens)])
            score = max(
                fuzz.ratio(normalized, candidate_prefix),
                fuzz.token_sort_ratio(normalized, candidate),
            )
            if score >= 82:
                row["match_score"] = score
                scored.append((score, row))
        scored.sort(
            key=lambda item: (
                -item[0],
                str(item[1].get("year") or ""),
                item[1]["full_name"],
            )
        )
        return [row for _, row in scored[:limit]]

    async def get_student(self, student_id: int) -> dict[str, Any] | None:
        def operation() -> dict[str, Any] | None:
            with self._connect() as db:
                row = db.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()
                return dict(row) if row else None

        return await asyncio.to_thread(operation)

    async def top_students(
        self,
        *,
        province: str | None = None,
        minimum_average: float = 95.0,
        limit: int = 10,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return verified high-achieving students ordered by average.

        A student is eligible only when the result is ``ناجح``, all seven
        core subject values are numeric and at least 50, and the stored
        average is between ``minimum_average`` and 100.
        """

        score_columns = (
            "islamic",
            "arabic",
            "english",
            "biology",
            "mathematics",
            "chemistry",
            "physics",
        )
        numeric_subject_checks = " AND ".join(
            f"({column} <> '' AND {column} NOT GLOB '*[^0-9]*' "
            f"AND CAST({column} AS INTEGER) BETWEEN 50 AND 100)"
            for column in score_columns
        )
        average_expression = (
            "CAST(REPLACE(REPLACE(TRIM(average), '%', ''), ',', '.') AS REAL)"
        )
        clauses = [
            "result='ناجح'",
            "TRIM(average) <> ''",
            f"{average_expression} BETWEEN ? AND 100",
            numeric_subject_checks,
        ]
        arguments: list[Any] = [float(minimum_average)]
        if province:
            clauses.append("province=?")
            arguments.append(province)
        where_sql = " AND ".join(clauses)

        def operation() -> tuple[list[dict[str, Any]], int]:
            with self._connect() as db:
                count_row = db.execute(
                    f"SELECT COUNT(*) FROM students WHERE {where_sql}",
                    arguments,
                ).fetchone()
                total = int(count_row[0] or 0)
                rows = db.execute(
                    f"""
                    WITH eligible AS (
                        SELECT *,
                               {average_expression} AS average_value,
                               CASE
                                   WHEN total <> '' AND total NOT GLOB '*[^0-9]*'
                                   THEN CAST(total AS INTEGER)
                                   ELSE 0
                               END AS total_value
                        FROM students
                        WHERE {where_sql}
                    ), ranked AS (
                        SELECT eligible.*,
                               RANK() OVER (
                                   ORDER BY average_value DESC, total_value DESC
                               ) AS honor_rank
                        FROM eligible
                    )
                    SELECT * FROM ranked
                    ORDER BY average_value DESC, total_value DESC, full_name
                    LIMIT ? OFFSET ?
                    """,
                    (*arguments, max(1, int(limit)), max(0, int(offset))),
                ).fetchall()
                return [dict(row) for row in rows], total

        return await asyncio.to_thread(operation)

    async def delete_scope(
        self, province: str, branch: str | None = None, year: str | None = None
    ) -> int:
        clauses = ["province=?"]
        args: list[Any] = [province]
        if branch:
            clauses.append("branch=?")
            args.append(branch)
        if year:
            clauses.append("year=?")
            args.append(year)

        def operation() -> int:
            with self._connect() as db:
                cursor = db.execute(
                    f"DELETE FROM students WHERE {' AND '.join(clauses)}", args
                )
                return int(cursor.rowcount or 0)

        async with self._write_lock:
            return await asyncio.to_thread(operation)
