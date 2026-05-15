from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)


ADMIN_MENU_TEXT = "Admin panel"


def admin_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎬 Yangi anime"), KeyboardButton(text="🗑 Anime o'chirish")],
            [KeyboardButton(text="📊 Statistika"), KeyboardButton(text="📣 Broadcast")],
            [KeyboardButton(text="🔐 Majburiy obuna")],
        ],
        resize_keyboard=True,
        selective=True,
    )


def finish_upload_keyboard(anime_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Done",
                    callback_data=f"anime_done:{anime_id}",
                ),
                InlineKeyboardButton(
                    text="❌ Bekor qilish",
                    callback_data=f"anime_cancel:{anime_id}",
                ),
            ]
        ]
    )


def upload_control_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✅ Done"), KeyboardButton(text="❌ Bekor qilish")],
        ],
        resize_keyboard=True,
        selective=True,
    )


def broadcast_target_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="👥 Userlar", callback_data="broadcast:users"),
                InlineKeyboardButton(text="📢 Guruh/Kanal", callback_data="broadcast:groups"),
            ],
            [InlineKeyboardButton(text="🌐 Hammasi", callback_data="broadcast:all")],
        ]
    )


def subscription_manage_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Yangilash", callback_data="sub_manage:update")],
            [InlineKeyboardButton(text="📋 Ro'yxat", callback_data="sub_manage:list")],
            [InlineKeyboardButton(text="🗑 O'chirish", callback_data="sub_manage:clear")],
        ]
    )


def forced_subscription_keyboard(
    channels: list[dict[str, str | None]],
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for index, channel in enumerate(channels, start=1):
        url = channel.get("invite_link")
        if not url:
            continue
        title = channel.get("title") or f"Kanal {index}"
        rows.append([InlineKeyboardButton(text=title, url=url)])
    rows.append([InlineKeyboardButton(text="✅ Tekshirish", callback_data="check_subscription")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def episode_navigation_keyboard(
    anime_id: int,
    episode_number: int,
    total_episodes: int,
) -> InlineKeyboardMarkup:
    buttons: list[InlineKeyboardButton] = []
    if episode_number > 1:
        buttons.append(
            InlineKeyboardButton(
                text="⬅️ Oldingi",
                callback_data=f"episode:{anime_id}:{episode_number - 1}",
            )
        )
    buttons.append(
        InlineKeyboardButton(
            text=f"{episode_number}/{total_episodes}",
            callback_data="episode:noop",
        )
    )
    if episode_number < total_episodes:
        buttons.append(
            InlineKeyboardButton(
                text="Keyingi ➡️",
                callback_data=f"episode:{anime_id}:{episode_number + 1}",
            )
        )
    return InlineKeyboardMarkup(inline_keyboard=[buttons])
