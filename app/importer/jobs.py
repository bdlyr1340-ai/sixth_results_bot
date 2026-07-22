from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import time
import zipfile
from collections.abc import Callable
from pathlib import Path
from urllib.parse import unquote, urlsplit

from app.config import Settings
from app.constants import PROVINCE_ALIASES
from app.database import Database, utc_now
from app.importer.decoder import decode_pdf_text, extract_best_mapping, text_needs_custom_decode
from app.importer.parser import parse_decoded_pdf
from app.importer.remote import decode_remote_source, discover_pdf_urls, download_pdf
from app.models import StudentRecord
from app.text_utils import normalize_arabic

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int, int, int], None]


def _safe_extract(archive: zipfile.ZipFile, destination: Path) -> None:
    destination_resolved = destination.resolve()
    for member in archive.infolist():
        target = (destination / member.filename).resolve()
        if destination_resolved not in target.parents and target != destination_resolved:
            raise ValueError(f"Unsafe path in ZIP: {member.filename}")
    archive.extractall(destination)


def _pdftotext(pdf_path: Path) -> str:
    process = subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), "-"],
        check=True,
        capture_output=True,
        timeout=120,
    )
    return process.stdout.decode("utf-8", "replace")


def _parse_pdf(pdf_path: Path, job: dict, source_file: str) -> list[StudentRecord]:
    raw = _pdftotext(pdf_path)
    local_mapping = extract_best_mapping(pdf_path) if text_needs_custom_decode(raw) else None
    decoded = decode_pdf_text(raw, local_mapping)
    return parse_decoded_pdf(
        decoded,
        province=job["province"],
        branch=job["branch"],
        year=job["year"],
        exam_round=job["exam_round"],
        source_file=source_file,
        import_id=int(job["id"]),
    )


def _process_archive_sync(
    job: dict,
    work_root: Path,
    progress: ProgressCallback | None = None,
) -> tuple[list[StudentRecord], int, list[str]]:
    archive_path = Path(job["archive_path"])
    if not archive_path.exists():
        raise FileNotFoundError(f"Archive not found: {archive_path}")
    if not zipfile.is_zipfile(archive_path):
        raise ValueError("الملف المرفوع ليس ZIP صالحًا")

    work_dir = work_root / f"import-{job['id']}"
    shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(archive_path) as archive:
        _safe_extract(archive, work_dir)

    pdf_files = sorted(path for path in work_dir.rglob("*.pdf") if path.is_file())
    if not pdf_files:
        raise ValueError("ملف ZIP لا يحتوي على ملفات PDF")

    errors: list[str] = []
    records: list[StudentRecord] = []

    for index, pdf_path in enumerate(pdf_files):
        try:
            parsed = _parse_pdf(pdf_path, job, pdf_path.name)
            if not parsed:
                errors.append(f"{pdf_path.name}: لم يتم العثور على صفوف طلاب")
            records.extend(parsed)
        except Exception as exc:
            errors.append(f"{pdf_path.name}: {exc}")
        finally:
            processed = index + 1
            if progress and (processed == 1 or processed % 10 == 0 or processed == len(pdf_files)):
                progress(processed, len(pdf_files), len(records), len(errors))

    shutil.rmtree(work_dir, ignore_errors=True)
    return records, len(pdf_files), errors


def _process_remote_sync(
    job: dict,
    settings: Settings,
    progress: ProgressCallback | None = None,
) -> tuple[list[StudentRecord], int, list[str]]:
    source_urls = decode_remote_source(str(job["archive_path"]))
    pdf_urls = discover_pdf_urls(
        source_urls,
        timeout=settings.remote_request_timeout,
        max_pdfs=settings.remote_max_pdfs,
        max_depth=settings.remote_max_depth,
    )
    total_files = len(pdf_urls)
    if progress:
        progress(0, total_files, 0, 0)

    work_dir = settings.storage_dir / "work" / f"remote-import-{job['id']}"
    shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    errors: list[str] = []
    records: list[StudentRecord] = []
    try:
        for index, pdf_url in enumerate(pdf_urls):
            original_name = Path(unquote(urlsplit(pdf_url).path)).name or f"result-{index + 1}.pdf"
            local_path = work_dir / f"{index + 1:05d}-{original_name}"
            try:
                download_pdf(
                    pdf_url,
                    local_path,
                    timeout=settings.remote_request_timeout,
                )
                parsed = _parse_pdf(local_path, job, original_name)
                if not parsed:
                    errors.append(f"{original_name}: لم يتم العثور على صفوف طلاب")
                records.extend(parsed)
            except Exception as exc:
                errors.append(f"{original_name}: {exc}")
            finally:
                local_path.unlink(missing_ok=True)
                processed = index + 1
                if progress and (
                    processed == 1 or processed % 5 == 0 or processed == total_files
                ):
                    progress(processed, total_files, len(records), len(errors))
                if settings.remote_delay_ms > 0 and processed < total_files:
                    time.sleep(settings.remote_delay_ms / 1000)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    return records, total_files, errors


def _province_matches(selected: str, records: list[StudentRecord]) -> bool:
    directorates = {normalize_arabic(record.directorate) for record in records[:500] if record.directorate}
    if not directorates:
        return True
    aliases = tuple(normalize_arabic(item) for item in PROVINCE_ALIASES.get(selected, (selected,)))
    return any(any(alias in directorate for alias in aliases) for directorate in directorates)


class ImportManager:
    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings
        self._tasks: dict[int, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    async def resume_pending(self) -> None:
        for import_id in await self.db.pending_import_ids():
            await self.enqueue(import_id)

    async def enqueue(self, import_id: int) -> None:
        async with self._lock:
            current = self._tasks.get(import_id)
            if current and not current.done():
                return
            self._tasks[import_id] = asyncio.create_task(
                self._run(import_id), name=f"import-{import_id}"
            )

    async def _run(self, import_id: int) -> None:
        job = await self.db.get_import(import_id)
        if not job:
            return
        await self.db.update_import(
            import_id,
            status="processing",
            started_at=utc_now(),
            error_log="",
            error_count=0,
            processed_files=0,
            student_count=0,
        )
        try:
            loop = asyncio.get_running_loop()

            def progress(processed: int, total: int, students: int, errors_count: int) -> None:
                asyncio.run_coroutine_threadsafe(
                    self.db.update_import(
                        import_id,
                        total_files=total,
                        processed_files=processed,
                        student_count=students,
                        error_count=errors_count,
                    ),
                    loop,
                )

            is_remote = str(job["archive_path"]).startswith("remote:")
            if is_remote:
                records, total_files, errors = await asyncio.to_thread(
                    _process_remote_sync,
                    job,
                    self.settings,
                    progress,
                )
            else:
                records, total_files, errors = await asyncio.to_thread(
                    _process_archive_sync,
                    job,
                    self.settings.storage_dir / "work",
                    progress,
                )

            await self.db.update_import(
                import_id,
                total_files=total_files,
                processed_files=total_files,
                error_count=len(errors),
                error_log="\n".join(errors[-200:]),
            )
            if not records:
                raise RuntimeError("لم تُستخرج أي نتيجة طالب من المصدر")
            if not _province_matches(job["province"], records):
                raise RuntimeError(
                    "المحافظة المختارة لا تطابق المديرية المكتوبة داخل ملفات PDF. "
                    "استخدم رابط أو ملف المحافظة الصحيح."
                )
            if errors and bool(job["replace_existing"]):
                raise RuntimeError(
                    f"توقفت عملية الاستبدال لحماية البيانات لأن {len(errors)} ملفًا لم يُقرأ بصورة كاملة. "
                    "راجع سجل التنبيهات وأعد المحاولة."
                )
            inserted = await self.db.replace_scope_and_insert(
                import_id,
                records,
                replace_existing=bool(job["replace_existing"]),
            )
            await self.db.update_import(
                import_id,
                status="completed" if not errors else "completed_with_errors",
                student_count=inserted,
                finished_at=utc_now(),
            )
        except Exception as exc:
            logger.exception("Import %s failed", import_id)
            latest = await self.db.get_import(import_id) or job
            await self.db.update_import(
                import_id,
                status="failed",
                error_count=max(1, int(latest.get("error_count") or 0)),
                error_log=str(exc),
                finished_at=utc_now(),
            )
