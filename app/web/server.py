from __future__ import annotations

import asyncio
import secrets
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.config import Settings
from app.constants import PROVINCES
from app.database import Database
from app.importer.jobs import ImportManager

TEMPLATES_DIR = Path(__file__).parent / "templates"


def create_web_app(settings: Settings, db: Database, manager: ImportManager) -> FastAPI:
    app = FastAPI(title="لوحة إدارة نتائج السادس", docs_url=None, redoc_url=None)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.web_session_secret,
        same_site="lax",
        https_only=settings.public_base_url.startswith("https://"),
        max_age=60 * 60 * 12,
    )
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    def is_logged_in(request: Request) -> bool:
        return bool(request.session.get("owner_logged_in"))

    def require_login(request: Request) -> None:
        if not is_logged_in(request):
            raise HTTPException(status_code=401, detail="Login required")

    @app.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:
        return RedirectResponse("/admin")

    @app.get("/health", include_in_schema=False)
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/admin/login", response_class=HTMLResponse, include_in_schema=False)
    async def login_page(request: Request, error: str = "") -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": error},
        )

    @app.post("/admin/login", include_in_schema=False)
    async def login(
        request: Request,
        username: str = Form(...),
        password: str = Form(...),
    ) -> RedirectResponse:
        valid_user = secrets.compare_digest(username, settings.web_admin_username)
        valid_password = secrets.compare_digest(password, settings.web_admin_password)
        if not (valid_user and valid_password):
            return RedirectResponse("/admin/login?error=1", status_code=303)
        request.session.clear()
        request.session["owner_logged_in"] = True
        return RedirectResponse("/admin", status_code=303)

    @app.post("/admin/logout", include_in_schema=False)
    async def logout(request: Request) -> RedirectResponse:
        request.session.clear()
        return RedirectResponse("/admin/login", status_code=303)

    @app.get("/admin", response_class=HTMLResponse, include_in_schema=False)
    async def dashboard(request: Request):
        if not is_logged_in(request):
            return RedirectResponse("/admin/login", status_code=303)
        stats, province_stats, imports = await asyncio.gather(
            db.dashboard_stats(),
            db.province_stats(),
            db.list_imports(limit=20),
        )
        return templates.TemplateResponse(
            request=request,
            name="dashboard.html",
            context={
                "stats": stats,
                "provinces": province_stats,
                "imports": imports,
                "default_year": "2025/2026",
                "default_round": "الأول",
                "default_branch": "علمي",
            },
        )

    @app.post("/admin/upload", include_in_schema=False)
    async def upload_archive(
        request: Request,
        province: str = Form(...),
        branch: str = Form("علمي"),
        year: str = Form("2025/2026"),
        exam_round: str = Form("الأول"),
        replace_existing: str | None = Form(None),
        archive: UploadFile = File(...),
    ) -> RedirectResponse:
        require_login(request)
        if province not in PROVINCES:
            raise HTTPException(status_code=400, detail="محافظة غير صالحة")
        if not archive.filename or not archive.filename.lower().endswith(".zip"):
            raise HTTPException(status_code=400, detail="يجب رفع ملف ZIP")

        safe_name = f"{uuid4().hex}-{Path(archive.filename).name}"
        destination = settings.storage_dir / "uploads" / safe_name
        size = 0
        with destination.open("wb") as output:
            while chunk := await archive.read(1024 * 1024):
                size += len(chunk)
                if size > 1024 * 1024 * 1024:
                    output.close()
                    destination.unlink(missing_ok=True)
                    raise HTTPException(status_code=413, detail="حجم الملف أكبر من 1GB")
                output.write(chunk)

        import_id = await db.create_import(
            province=province,
            branch=branch.strip() or "علمي",
            year=year.strip() or "2025/2026",
            exam_round=exam_round.strip() or "الأول",
            archive_name=Path(archive.filename).name,
            archive_path=str(destination),
            replace_existing=replace_existing == "on",
        )
        await manager.enqueue(import_id)
        return RedirectResponse(f"/admin/imports/{import_id}", status_code=303)

    @app.get("/admin/imports/{import_id}", response_class=HTMLResponse, include_in_schema=False)
    async def import_status(request: Request, import_id: int):
        if not is_logged_in(request):
            return RedirectResponse("/admin/login", status_code=303)
        job = await db.get_import(import_id)
        if not job:
            raise HTTPException(status_code=404, detail="عملية الرفع غير موجودة")
        return templates.TemplateResponse(
            request=request,
            name="import_status.html",
            context={"job": job},
        )

    @app.post("/admin/delete-province", include_in_schema=False)
    async def delete_province(
        request: Request,
        province: str = Form(...),
        confirm: str = Form(""),
    ) -> RedirectResponse:
        require_login(request)
        if province not in PROVINCES or confirm.strip() != province:
            raise HTTPException(status_code=400, detail="تأكيد الحذف غير صحيح")
        await db.delete_scope(province)
        return RedirectResponse("/admin", status_code=303)

    return app
