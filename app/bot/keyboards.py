from __future__ import annotations

from aiogram.types import CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.constants import PROVINCES


def main_menu(is_owner: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔍 البحث عن نتيجة", callback_data="search:start")
    builder.button(text="🏆 الطلاب المتفوقون", callback_data="leaders:menu")
    builder.button(text="❤️ دعم البوت", callback_data="donation")
    builder.button(text="ℹ️ طريقة الاستخدام", callback_data="help")
    builder.button(text="⚠️ الإبلاغ عن خطأ", callback_data="report:start")
    if is_owner:
        builder.button(text="👑 لوحة المالك", callback_data="admin:panel")
    builder.adjust(1, 1, 2, 1, 1)
    return builder.as_markup()


def leaders_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🥇 أوائل العراق", callback_data="leaders:list:all:0")],
            [InlineKeyboardButton(text="🗺️ المتفوقون حسب المحافظة", callback_data="leaders:provinces")],
            [InlineKeyboardButton(text="🏠 الرئيسية", callback_data="home")],
        ]
    )


def leaders_provinces_keyboard(stats: list[dict]) -> InlineKeyboardMarkup:
    by_name = {row["province"]: row for row in stats}
    builder = InlineKeyboardBuilder()
    for index, province in enumerate(PROVINCES):
        count = int(by_name.get(province, {}).get("student_count") or 0)
        if count:
            builder.button(text=province, callback_data=f"leaders:list:p:{index}:0")
    builder.button(text="🔙 رجوع", callback_data="leaders:menu")
    builder.button(text="🏠 الرئيسية", callback_data="home")
    builder.adjust(2, 2, 2, 2, 2, 2, 2, 2, 2, 1, 1)
    return builder.as_markup()


def leaders_page_keyboard(
    *,
    scope: str,
    page: int,
    has_previous: bool,
    has_next: bool,
    province_index: int | None = None,
) -> InlineKeyboardMarkup:
    if scope == "all":
        callback_prefix = "leaders:list:all"
    else:
        callback_prefix = f"leaders:list:p:{province_index}"

    navigation: list[InlineKeyboardButton] = []
    if has_previous:
        navigation.append(
            InlineKeyboardButton(
                text="➡️ السابق",
                callback_data=f"{callback_prefix}:{page - 1}",
            )
        )
    if has_next:
        navigation.append(
            InlineKeyboardButton(
                text="التالي ⬅️",
                callback_data=f"{callback_prefix}:{page + 1}",
            )
        )

    rows: list[list[InlineKeyboardButton]] = []
    if navigation:
        rows.append(navigation)
    if scope == "all":
        rows.append(
            [InlineKeyboardButton(text="🗺️ حسب المحافظة", callback_data="leaders:provinces")]
        )
    else:
        rows.append(
            [InlineKeyboardButton(text="🔄 تغيير المحافظة", callback_data="leaders:provinces")]
        )
        rows.append(
            [InlineKeyboardButton(text="🥇 أوائل العراق", callback_data="leaders:list:all:0")]
        )
    rows.append([InlineKeyboardButton(text="🏠 الرئيسية", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def provinces_keyboard(stats: list[dict]) -> InlineKeyboardMarkup:
    by_name = {row["province"]: row for row in stats}
    builder = InlineKeyboardBuilder()
    for index, province in enumerate(PROVINCES):
        count = int(by_name.get(province, {}).get("student_count") or 0)
        label = f"{province} ({count:,})" if count else f"{province} - قريبًا"
        builder.button(
            text=label,
            callback_data=f"province:{index}" if count else f"unavailable:{index}",
        )
    builder.button(text="🔙 رجوع", callback_data="home")
    builder.adjust(2, 2, 2, 2, 2, 2, 2, 2, 2, 1)
    return builder.as_markup()


def waiting_name_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🗺️ تغيير المحافظة", callback_data="search:start"),
                InlineKeyboardButton(text="❌ إلغاء", callback_data="home"),
            ]
        ]
    )


def no_results_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ إعادة كتابة الاسم", callback_data="search:retry")],
            [InlineKeyboardButton(text="🗺️ تغيير المحافظة", callback_data="search:start")],
            [InlineKeyboardButton(text="⚠️ الإبلاغ عن اسم مفقود", callback_data="report:start")],
            [InlineKeyboardButton(text="🔙 القائمة الرئيسية", callback_data="home")],
        ]
    )


def matches_keyboard(rows: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for row in rows:
        school = row.get("school_name") or "مدرسة غير محددة"
        year = row.get("year") or ""
        title = f"{row['full_name']} - {school} - {year}"
        if len(title) > 60:
            title = title[:57] + "..."
        builder.button(text=title, callback_data=f"student:{row['id']}")
    builder.button(text="✏️ إعادة البحث", callback_data="search:retry")
    builder.button(text="🔙 الرئيسية", callback_data="home")
    builder.adjust(1)
    return builder.as_markup()


def result_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔍 بحث جديد", callback_data="search:start"),
                InlineKeyboardButton(text="❤️ دعم البوت", callback_data="donation"),
            ],
            [InlineKeyboardButton(text="⚠️ الإبلاغ عن خطأ", callback_data="report:start")],
            [InlineKeyboardButton(text="🏠 الرئيسية", callback_data="home")],
        ]
    )


def donation_keyboard(number: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📋 نسخ رقم سوبر كي",
                    copy_text=CopyTextButton(text=number),
                )
            ],
            [InlineKeyboardButton(text="🔙 رجوع", callback_data="home")],
        ]
    )


def report_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ إلغاء", callback_data="home")]]
    )


def admin_keyboard(dashboard_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📦 رفع ملفات المحافظات", url=dashboard_url)],
            [
                InlineKeyboardButton(text="📊 تحديث العدادات", callback_data="admin:panel"),
                InlineKeyboardButton(text="🗂️ آخر عمليات الرفع", callback_data="admin:imports"),
            ],
            [InlineKeyboardButton(text="🏠 الرئيسية", callback_data="home")],
        ]
    )
