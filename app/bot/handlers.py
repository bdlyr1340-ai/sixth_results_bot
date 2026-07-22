from __future__ import annotations

import html
import logging
from typing import Any

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards import (
    donation_keyboard,
    main_menu,
    matches_keyboard,
    no_results_keyboard,
    provinces_keyboard,
    report_cancel_keyboard,
    result_keyboard,
    waiting_name_keyboard,
)
from app.bot.states import SearchStates
from app.config import Settings
from app.constants import PROVINCES, SUBJECTS
from app.database import Database
from app.text_utils import valid_search_name

logger = logging.getLogger(__name__)
router = Router(name="public")


def _is_owner(user_id: int | None, settings: Settings) -> bool:
    return bool(user_id and user_id == settings.owner_id)


def _score_icon(value: str) -> str:
    if not value:
        return "▫️"
    if value in {"م", "غ", "غائب", "مؤجل", "مؤجلة"}:
        return "⚠️"
    try:
        number = int(value.rstrip("%"))
        return "✅" if number >= 50 else "❌"
    except ValueError:
        return "▫️"


def format_student(row: dict[str, Any]) -> str:
    lines = [
        "🎓 <b>نتيجة السادس الإعدادي</b>",
        "",
        f"👤 <b>الاسم:</b> {html.escape(row['full_name'])}",
        f"🏫 <b>المدرسة:</b> {html.escape(row.get('school_name') or 'غير محددة')}",
        f"📍 <b>المحافظة:</b> {html.escape(row['province'])}",
        f"🧭 <b>الفرع:</b> {html.escape(row.get('branch') or '')}",
        f"📅 <b>السنة والدور:</b> {html.escape(row.get('year') or '')} - {html.escape(row.get('exam_round') or '')}",
        f"🆔 <b>الرقم الامتحاني:</b> <code>{html.escape(row['exam_number'])}</code>",
        "",
        "──────────────",
    ]
    for key, label in SUBJECTS:
        value = str(row.get(key) or "-")
        if key == "languages" and value == "-":
            continue
        lines.append(f"{_score_icon(value)} <b>{label}:</b> {html.escape(value)}")
    lines.extend(
        [
            "──────────────",
            f"📊 <b>المجموع:</b> {html.escape(str(row.get('total') or '-'))}",
            f"📈 <b>المعدل:</b> {html.escape(str(row.get('average') or '-'))}",
            f"📌 <b>النتيجة:</b> {html.escape(str(row.get('result') or '-'))}",
            "",
            "النتيجة من الملف الرسمي المرفوع إلى قاعدة بيانات البوت.",
        ]
    )
    return "\n".join(lines)


async def _show_home(message_or_callback: Message | CallbackQuery, settings: Settings) -> None:
    user = message_or_callback.from_user
    text = (
        "🎓 <b>بوت نتائج السادس الإعدادي</b>\n\n"
        "اختر المحافظة، ثم اكتب الاسم الثلاثي أو الرباعي للبحث عن النتيجة.\n"
        "الخدمة مجانية لمساعدة الطلبة 🤍"
    )
    markup = main_menu(_is_owner(user.id if user else None, settings))
    if isinstance(message_or_callback, CallbackQuery):
        await message_or_callback.message.edit_text(text, reply_markup=markup)
        await message_or_callback.answer()
    else:
        await message_or_callback.answer(text, reply_markup=markup)


@router.message(CommandStart())
async def start(message: Message, state: FSMContext, settings: Settings, db: Database) -> None:
    await state.clear()
    await db.touch_user(message.from_user.id)
    await _show_home(message, settings)


@router.message(Command("id"))
async def show_id(message: Message) -> None:
    await message.answer(f"معرف حسابك في تيليغرام:\n<code>{message.from_user.id}</code>")


@router.callback_query(F.data == "home")
async def home(callback: CallbackQuery, state: FSMContext, settings: Settings) -> None:
    await state.clear()
    await _show_home(callback, settings)


@router.callback_query(F.data == "help")
async def help_callback(callback: CallbackQuery, settings: Settings) -> None:
    await callback.message.edit_text(
        "ℹ️ <b>طريقة الاستخدام</b>\n\n"
        "1. اضغط البحث عن نتيجة.\n"
        "2. اختر المحافظة.\n"
        "3. اكتب الاسم الثلاثي أو الرباعي فقط.\n"
        "4. عند تشابه الأسماء اختر المدرسة الصحيحة.\n\n"
        "مثال: <code>غدير ميثاق إبراهيم</code>",
        reply_markup=main_menu(_is_owner(callback.from_user.id, settings)),
    )
    await callback.answer()


@router.callback_query(F.data == "search:start")
async def choose_province(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    await state.clear()
    stats = await db.province_stats()
    await callback.message.edit_text(
        "🗺️ <b>اختر المحافظة</b>\n\nالمحافظات التي لا تحتوي بيانات تظهر بعبارة قريبًا.",
        reply_markup=provinces_keyboard(stats),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("unavailable:"))
async def unavailable(callback: CallbackQuery) -> None:
    await callback.answer("ملفات هذه المحافظة لم تُرفع بعد.", show_alert=True)


@router.callback_query(F.data.startswith("province:"))
async def province_selected(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        index = int(callback.data.split(":", 1)[1])
        province = PROVINCES[index]
    except (ValueError, IndexError):
        await callback.answer("اختيار غير صالح", show_alert=True)
        return
    await state.set_state(SearchStates.waiting_for_name)
    await state.update_data(province=province)
    await callback.message.edit_text(
        f"تم اختيار <b>{province}</b> ✅\n\n"
        "أرسل الآن اسم الطالب الثلاثي أو الرباعي.\n"
        "مثال: <code>غدير ميثاق إبراهيم</code>",
        reply_markup=waiting_name_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "search:retry")
async def retry_search(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    province = data.get("province")
    if not province:
        await callback.answer("اختر المحافظة أولًا", show_alert=True)
        return
    await state.set_state(SearchStates.waiting_for_name)
    await callback.message.edit_text(
        f"المحافظة: <b>{province}</b>\n\nأرسل الاسم الثلاثي أو الرباعي مرة أخرى:",
        reply_markup=waiting_name_keyboard(),
    )
    await callback.answer()


@router.message(SearchStates.waiting_for_name, F.text)
async def receive_name(message: Message, state: FSMContext, db: Database) -> None:
    query = message.text.strip()
    if not valid_search_name(query):
        await message.answer(
            "الرجاء إرسال اسم ثلاثي أو رباعي واضح، من دون أرقام أو ألقاب.\n"
            "مثال: <code>نبأ ليث جاسم</code>",
            reply_markup=waiting_name_keyboard(),
        )
        return
    data = await state.get_data()
    province = data.get("province")
    if not province:
        await state.clear()
        await message.answer("انتهت جلسة البحث. ابدأ من جديد.")
        return

    await db.touch_user(message.from_user.id, increment_search=True)
    rows = await db.search_students(province, query)
    await db.log_search(province, bool(rows))

    if not rows:
        await message.answer(
            "لم أعثر على الاسم بهذه الكتابة.\n\n"
            "تأكد من المحافظة، وجرّب الاسم الثلاثي من دون لقب العائلة.",
            reply_markup=no_results_keyboard(),
        )
        return

    if len(rows) == 1:
        await state.clear()
        await message.answer(format_student(rows[0]), reply_markup=result_keyboard())
        return

    await state.update_data(last_query=query)
    await message.answer(
        f"عثرت على <b>{len(rows)}</b> نتائج متشابهة. اختر الاسم والمدرسة الصحيحين:",
        reply_markup=matches_keyboard(rows),
    )


@router.callback_query(F.data.startswith("student:"))
async def selected_student(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    try:
        student_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("معرف غير صالح", show_alert=True)
        return
    row = await db.get_student(student_id)
    if not row:
        await callback.answer("النتيجة لم تعد موجودة", show_alert=True)
        return
    await state.clear()
    await callback.message.edit_text(format_student(row), reply_markup=result_keyboard())
    await callback.answer()


@router.callback_query(F.data == "donation")
async def donation(callback: CallbackQuery, settings: Settings) -> None:
    await callback.message.edit_text(
        "❤️ <b>دعم استمرار البوت</b>\n\n"
        "البوت مجاني بالكامل، والدعم اختياري للمساهمة في الاستضافة وإضافة المحافظات.\n\n"
        "<b>طريقة الدعم:</b> سوبر كي\n"
        f"<b>رقم التحويل:</b> <code>{html.escape(settings.donation_number)}</code>\n\n"
        "شكرًا لكل شخص يساهم باستمرار المشروع 🌹",
        reply_markup=donation_keyboard(settings.donation_number),
    )
    await callback.answer()


@router.callback_query(F.data == "report:start")
async def report_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SearchStates.waiting_for_report)
    await callback.message.edit_text(
        "⚠️ أرسل وصف الخطأ الآن.\n"
        "اكتب الاسم والمحافظة وما المشكلة، من دون إرسال معلومات غير ضرورية.",
        reply_markup=report_cancel_keyboard(),
    )
    await callback.answer()


@router.message(SearchStates.waiting_for_report, F.text)
async def report_receive(message: Message, state: FSMContext, bot: Bot, settings: Settings) -> None:
    text = message.text.strip()[:3000]
    sender = html.escape(message.from_user.full_name)
    username = f"@{message.from_user.username}" if message.from_user.username else "بدون معرف"
    await bot.send_message(
        settings.owner_id,
        "⚠️ <b>بلاغ جديد من البوت</b>\n\n"
        f"المرسل: {sender}\n"
        f"المعرف: {html.escape(username)}\n"
        f"Telegram ID: <code>{message.from_user.id}</code>\n\n"
        f"{html.escape(text)}",
    )
    await state.clear()
    await message.answer(
        "تم إرسال البلاغ إلى مالك البوت، شكرًا لك.",
        reply_markup=main_menu(_is_owner(message.from_user.id, settings)),
    )
