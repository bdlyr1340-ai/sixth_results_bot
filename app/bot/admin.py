from __future__ import annotations

import html

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards import admin_keyboard
from app.config import Settings
from app.database import Database

router = Router(name="admin")


def _allowed(user_id: int | None, settings: Settings) -> bool:
    return bool(user_id and user_id == settings.owner_id)


def _status_label(status: str) -> str:
    return {
        "queued": "بانتظار المعالجة",
        "processing": "جاري الفهرسة",
        "completed": "مكتمل",
        "completed_with_errors": "مكتمل مع تنبيهات",
        "failed": "فشل",
    }.get(status, status)


async def _panel_text(db: Database) -> str:
    stats = await db.dashboard_stats()
    provinces = await db.province_stats()
    available = [row for row in provinces if row["student_count"]]
    lines = [
        "👑 <b>لوحة مالك البوت</b>",
        "",
        f"👥 المستخدمون: <b>{stats['users']:,}</b>",
        f"🔎 عمليات البحث: <b>{stats['searches']:,}</b>",
        f"✅ نسبة العثور: <b>{stats['success_rate']}%</b>",
        f"🎓 الطلاب المفهرسون: <b>{stats['students']:,}</b>",
        f"📄 ملفات PDF: <b>{stats['files']:,}</b>",
        f"🗺️ المحافظات المتوفرة: <b>{stats['provinces']}</b>",
        "",
        "<b>تفاصيل المحافظات:</b>",
    ]
    if not available:
        lines.append("لا توجد ملفات مفهرسة بعد.")
    else:
        for row in available:
            lines.append(
                f"• {html.escape(row['province'])}: "
                f"{int(row['student_count']):,} طالب - {int(row['file_count']):,} ملف"
            )
    return "\n".join(lines)


@router.message(Command("admin"))
async def admin_command(message: Message, settings: Settings, db: Database) -> None:
    if not _allowed(message.from_user.id, settings):
        return
    await message.answer(
        await _panel_text(db),
        reply_markup=admin_keyboard(f"{settings.public_base_url}/admin"),
    )


@router.callback_query(F.data == "admin:panel")
async def admin_panel(callback: CallbackQuery, settings: Settings, db: Database) -> None:
    if not _allowed(callback.from_user.id, settings):
        await callback.answer("هذا القسم لمالك البوت فقط", show_alert=True)
        return
    await callback.message.edit_text(
        await _panel_text(db),
        reply_markup=admin_keyboard(f"{settings.public_base_url}/admin"),
    )
    await callback.answer()


@router.callback_query(F.data == "admin:imports")
async def admin_imports(callback: CallbackQuery, settings: Settings, db: Database) -> None:
    if not _allowed(callback.from_user.id, settings):
        await callback.answer("هذا القسم لمالك البوت فقط", show_alert=True)
        return
    imports = await db.list_imports(limit=10)
    lines = ["🗂️ <b>آخر عمليات رفع الملفات</b>", ""]
    if not imports:
        lines.append("لا توجد عمليات رفع بعد.")
    for job in imports:
        lines.extend(
            [
                f"<b>#{job['id']} - {html.escape(job['province'])}</b>",
                f"الحالة: {_status_label(job['status'])}",
                f"الملفات: {job['processed_files']}/{job['total_files']}",
                f"الطلاب: {job['student_count']:,}",
                f"الأخطاء: {job['error_count']}",
                "",
            ]
        )
    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=admin_keyboard(f"{settings.public_base_url}/admin"),
    )
    await callback.answer()
