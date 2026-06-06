from __future__ import annotations

import asyncio
import logging
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramUnauthorizedError
from aiogram.filters import BaseFilter, Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Chat, Message, User

from app.config import load_config, parse_chat_ref
from app.database import Database
from app.keyboards import (
    admin_menu_keyboard,
    anime_status_keyboard,
    broadcast_target_keyboard,
    episode_navigation_keyboard,
    forced_subscription_keyboard,
    subscription_manage_keyboard,
    upload_control_keyboard,
)
from app.states import AddAnimeStates, BroadcastStates, DeleteAnimeStates, SubscriptionStates


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

config = load_config()
db = Database(config.database_path)
router = Router()

BOT_NAME = "AniLow"
BOT_TAG = "#AniLow"

EPISODE_CONTENT_TYPES = {
    "animation",
    "audio",
    "document",
    "photo",
    "text",
    "video",
    "video_note",
    "voice",
}
CAPTION_COMPATIBLE_TYPES = {
    "animation",
    "audio",
    "document",
    "photo",
    "video",
    "voice",
}
ANIME_STATUS_LABELS = {
    "completed": "Tugagan",
    "ongoing": "Ongoing",
}
ANIME_STATUS_INPUTS = {
    "✅ tugagan": "completed",
    "tugagan": "completed",
    "yakunlangan": "completed",
    "completed": "completed",
    "🔄 ongoing": "ongoing",
    "ongoing": "ongoing",
    "davom etmoqda": "ongoing",
}
MEDIA_GROUP_COLLECT_DELAY = 1.2
media_group_lock = asyncio.Lock()
media_group_buffers: dict[tuple[int, str], dict[str, Any]] = {}
anime_upload_locks: dict[int, asyncio.Lock] = {}


def get_anime_upload_lock(anime_id: int) -> asyncio.Lock:
    if anime_id not in anime_upload_locks:
        anime_upload_locks[anime_id] = asyncio.Lock()
    return anime_upload_locks[anime_id]


class AdminFilter(BaseFilter):
    async def __call__(self, message: Message | CallbackQuery) -> bool:
        user_id = message.from_user.id if message.from_user else 0
        return user_id in config.admin_ids


admin_filter = AdminFilter()


def is_admin(user_id: int | None) -> bool:
    return bool(user_id in config.admin_ids) if user_id else False


def track_chat(chat: Chat, user: User | None) -> None:
    if chat.type == "private":
        full_name = user.full_name if user else chat.full_name
        username = user.username if user else chat.username
        title = None
    else:
        full_name = None
        username = chat.username
        title = chat.title

    db.upsert_chat(
        chat_id=chat.id,
        chat_type=chat.type,
        title=title,
        username=username,
        full_name=full_name,
    )


def normalize_subscription_input(raw: str) -> tuple[str, str | None]:
    value = raw.strip()
    if value.startswith("https://t.me/"):
        slug = value.removeprefix("https://t.me/").strip("/")
        if slug.startswith("+") or slug.startswith("joinchat/"):
            raise ValueError("Private invite link ishlamaydi. Public username yoki chat ID yuboring.")
        return f"@{slug}", value
    if value.startswith("t.me/"):
        slug = value.removeprefix("t.me/").strip("/")
        if slug.startswith("+") or slug.startswith("joinchat/"):
            raise ValueError("Private invite link ishlamaydi. Public username yoki chat ID yuboring.")
        return f"@{slug}", f"https://t.me/{slug}"
    if value.startswith("@"):
        username = value
        return username, f"https://t.me/{username[1:]}"
    if value.lstrip("-").isdigit():
        return value, None
    raise ValueError("Faqat @username, public t.me link yoki numeric chat ID yuboring.")


def build_hashtag(value: str) -> str:
    cleaned = re.sub(r"[^\w\s]", " ", value, flags=re.UNICODE)
    parts = [part for part in cleaned.split() if part]
    return f"#{'_'.join(parts)}" if parts else BOT_TAG


def build_branding_lines(anime: Any) -> list[str]:
    lines = [
        f"{BOT_TAG} | {build_hashtag(anime['title'])}",
        f"🎬 <b>{anime['title']}</b>",
    ]
    status = anime["status"] if "status" in anime.keys() else ""
    if status:
        lines.append(f"📌 Holat: <b>{ANIME_STATUS_LABELS.get(status, status)}</b>")
    return lines


def build_episode_text(anime: Any, episode_number: int) -> str:
    description = (anime["description"] or "").strip()
    lines = build_branding_lines(anime)
    lines.extend(
        [
            f"🆔 ID: <code>{anime['anime_id']}</code>",
            f"🎞 Qism: {episode_number}/{anime['episodes_count']}",
        ]
    )
    if description:
        lines.append("")
        lines.append(description)
    return "\n".join(lines)


def build_title_photo_caption(anime: Any) -> str:
    description = (anime["description"] or "").strip()
    lines = build_branding_lines(anime)
    lines.append(f"🆔 ID: <code>{anime['anime_id']}</code>")
    if description:
        lines.append("")
        lines.append(description)
    return "\n".join(lines)


async def ensure_subscription(bot: Bot, user_id: int, target_message: Message | CallbackQuery) -> bool:
    if is_admin(user_id):
        return True

    channels = db.get_subscription_channels()
    if not channels:
        return True

    unresolved: list[dict[str, str | None]] = []
    for channel in channels:
        chat_ref = parse_chat_ref(channel["chat_ref"])
        try:
            member = await bot.get_chat_member(chat_ref, user_id)
        except TelegramBadRequest:
            unresolved.append(dict(channel))
            continue

        if member.status in {"left", "kicked"}:
            unresolved.append(dict(channel))

    if not unresolved:
        return True

    prompt = (
        f"🔐 {BOT_NAME} dan foydalanish uchun quyidagi kanallarga obuna bo'ling, "
        "so'ng `Tekshirish` tugmasini bosing."
    )
    keyboard = forced_subscription_keyboard(unresolved)
    if isinstance(target_message, CallbackQuery):
        await target_message.message.answer(prompt, reply_markup=keyboard)
    else:
        await target_message.answer(prompt, reply_markup=keyboard)
    return False


async def send_title_photo(bot: Bot, chat_id: int, anime_id: int) -> None:
    anime = db.get_anime(anime_id)
    if not anime or not anime["title_photo_message_id"]:
        return

    await bot.copy_message(
        chat_id=chat_id,
        from_chat_id=config.storage_channel_id,
        message_id=anime["title_photo_message_id"],
        caption=build_title_photo_caption(anime),
    )


async def delete_anime_assets(bot: Bot, anime_id: int) -> None:
    message_ids = db.get_anime_storage_message_ids(anime_id)
    if not message_ids:
        return

    try:
        await bot.delete_messages(
            chat_id=config.storage_channel_id,
            message_ids=message_ids,
        )
    except TelegramBadRequest:
        for message_id in message_ids:
            try:
                await bot.delete_message(
                    chat_id=config.storage_channel_id,
                    message_id=message_id,
                )
            except TelegramBadRequest:
                continue


async def send_episode(
    bot: Bot,
    chat_id: int,
    anime_id: int,
    episode_number: int,
) -> None:
    anime = db.get_anime(anime_id)
    if not anime:
        await bot.send_message(chat_id, "❌ Anime topilmadi yoki hali yakunlanmagan.")
        return

    episode = db.get_episode(anime_id, episode_number)
    if not episode:
        await bot.send_message(chat_id, "❌ Bu qism topilmadi.")
        return

    text = build_episode_text(anime, episode_number)
    markup = episode_navigation_keyboard(
        anime_id=anime_id,
        episode_number=episode_number,
        total_episodes=anime["episodes_count"],
    )

    if episode["content_type"] in CAPTION_COMPATIBLE_TYPES:
        await bot.copy_message(
            chat_id=chat_id,
            from_chat_id=config.storage_channel_id,
            message_id=episode["storage_message_id"],
            caption=text,
            reply_markup=markup,
        )
        return

    await bot.copy_message(
        chat_id=chat_id,
        from_chat_id=config.storage_channel_id,
        message_id=episode["storage_message_id"],
    )
    await bot.send_message(chat_id, text, reply_markup=markup)


@router.message(CommandStart())
async def start_handler(message: Message) -> None:
    track_chat(message.chat, message.from_user)
    args = message.text.split(maxsplit=1)[1] if message.text and " " in message.text else ""
    if args.isdigit():
        if not await ensure_subscription(message.bot, message.from_user.id, message):
            return
        await send_title_photo(message.bot, message.chat.id, int(args))
        await send_episode(message.bot, message.chat.id, int(args), 1)
        return

    await message.answer(
        f"👋 Salom, {message.from_user.full_name}!\n\n"
        f"{BOT_TAG} ga xush kelibsiz.\n"
        "🎬 Anime ID yuboring.\n"
        "🔎 Masalan: <code>1001</code>"
    )


@router.message(Command("admin"), admin_filter)
async def admin_command_handler(message: Message, state: FSMContext) -> None:
    track_chat(message.chat, message.from_user)
    await state.clear()
    await message.answer(
        f"🛠 {BOT_NAME} admin panel ochildi.",
        reply_markup=admin_menu_keyboard(),
    )


@router.message(F.text == "🎬 Yangi anime", admin_filter)
async def new_anime_handler(message: Message, state: FSMContext) -> None:
    track_chat(message.chat, message.from_user)
    await state.clear()
    await state.set_state(AddAnimeStates.waiting_id)
    await message.answer("🆔 Anime uchun raqamli ID yuboring.\n🎯 Masalan: <code>1001</code>")


@router.message(F.text == "🗑 Anime o'chirish", admin_filter)
async def delete_anime_menu_handler(message: Message, state: FSMContext) -> None:
    track_chat(message.chat, message.from_user)
    await state.clear()
    await state.set_state(DeleteAnimeStates.waiting_id)
    await message.answer("🗑 O'chiriladigan anime ID sini yuboring.\n🎯 Masalan: <code>1001</code>")


@router.message(AddAnimeStates.waiting_id, admin_filter)
async def anime_id_handler(message: Message, state: FSMContext) -> None:
    track_chat(message.chat, message.from_user)
    if not message.text or not message.text.isdigit():
        await message.answer("⚠️ ID faqat raqamdan iborat bo'lishi kerak.")
        return

    anime_id = int(message.text)
    if db.anime_exists(anime_id):
        await message.answer("⚠️ Bu ID allaqachon ishlatilgan.\n🔁 Boshqa ID yuboring.")
        return

    await state.update_data(anime_id=anime_id)
    await state.set_state(AddAnimeStates.waiting_title)
    await message.answer("📝 Anime nomini yuboring.")


@router.message(AddAnimeStates.waiting_title, admin_filter)
async def anime_title_handler(message: Message, state: FSMContext) -> None:
    track_chat(message.chat, message.from_user)
    if not message.text:
        await message.answer("⚠️ Anime nomini matn ko'rinishida yuboring.")
        return

    await state.update_data(title=message.text.strip())
    await state.set_state(AddAnimeStates.waiting_description)
    await message.answer(
        "📄 Barcha qismlar ostida chiqadigan umumiy matnni yuboring.\n"
        "➡️ Agar kerak bo'lmasa `-` yuboring."
    )


@router.message(AddAnimeStates.waiting_description, admin_filter)
async def anime_description_handler(message: Message, state: FSMContext) -> None:
    track_chat(message.chat, message.from_user)
    if not message.text:
        await message.answer("⚠️ Umumiy matnni matn ko'rinishida yuboring yoki `-` yozing.")
        return

    description = "" if message.text.strip() == "-" else message.text.strip()
    await state.update_data(description=description)
    await state.set_state(AddAnimeStates.waiting_title_photo)
    await message.answer("🖼 Endi anime uchun title rasmini yuboring.")


@router.message(AddAnimeStates.waiting_title_photo, admin_filter)
async def anime_title_photo_handler(message: Message, state: FSMContext) -> None:
    track_chat(message.chat, message.from_user)
    if not message.photo:
        await message.answer("⚠️ Title uchun rasmni photo ko'rinishida yuboring.")
        return

    data = await state.get_data()
    copied_message = await message.bot.copy_message(
        chat_id=config.storage_channel_id,
        from_chat_id=message.chat.id,
        message_id=message.message_id,
    )
    await state.update_data(title_photo_message_id=copied_message.message_id)
    await state.set_state(AddAnimeStates.waiting_status)
    await message.answer(
        "📌 Anime holatini tanlang.\n"
        "✅ Tugagan anime bo'lsa `Tugagan`, hali chiqayotgan bo'lsa `Ongoing` ni bosing.",
        reply_markup=anime_status_keyboard(),
    )


@router.message(AddAnimeStates.waiting_status, admin_filter)
async def anime_status_handler(message: Message, state: FSMContext) -> None:
    track_chat(message.chat, message.from_user)
    data = await state.get_data()
    if message.text == "❌ Bekor qilish":
        title_photo_message_id = data.get("title_photo_message_id")
        if title_photo_message_id:
            try:
                await message.bot.delete_message(
                    chat_id=config.storage_channel_id,
                    message_id=title_photo_message_id,
                )
            except TelegramBadRequest:
                pass
        await state.clear()
        await message.answer(
            "❌ Anime qo'shish jarayoni bekor qilindi.",
            reply_markup=admin_menu_keyboard(),
        )
        return

    status = ANIME_STATUS_INPUTS.get((message.text or "").strip().lower())
    if not status:
        await message.answer("⚠️ Holatni `Tugagan` yoki `Ongoing` deb tanlang.")
        return

    created = db.create_anime(
        anime_id=data["anime_id"],
        title=data["title"],
        description=data["description"],
        status=status,
        title_photo_message_id=data["title_photo_message_id"],
        created_by=message.from_user.id,
    )
    if not created:
        try:
            await message.bot.delete_message(
                chat_id=config.storage_channel_id,
                message_id=data["title_photo_message_id"],
            )
        except TelegramBadRequest:
            pass
        await state.clear()
        await message.answer(
            "⚠️ Bu ID allaqachon bor. Boshqa ID bilan qayta boshlang.",
            reply_markup=admin_menu_keyboard(),
        )
        return
    await state.set_state(AddAnimeStates.waiting_media)
    await message.answer(
        "📤 Endi qismlarni bittadan yuboring.\n"
        "⚠️ Telegram bir martada ko'pi bilan 10 ta media yuboradi, 10 tadan bo'lib yuboring.\n"
        "✅ Yuklash tugagach `Done` tugmasini bosing.",
        reply_markup=upload_control_keyboard(),
    )


@router.message(AddAnimeStates.waiting_media, F.text == "✅ Done", admin_filter)
async def anime_done_text_handler(message: Message, state: FSMContext) -> None:
    track_chat(message.chat, message.from_user)
    data = await state.get_data()
    anime_id = data["anime_id"]
    await wait_pending_media_group_uploads(anime_id)
    total = db.finalize_anime(anime_id)
    if total == 0:
        db.delete_anime(anime_id)
        await state.clear()
        await message.answer(
            "❌ Anime bekor qilindi, chunki qism yo'q.",
            reply_markup=admin_menu_keyboard(),
        )
        return

    await state.clear()
    await message.answer(
        f"✅ Anime saqlandi.\n🆔 ID: <code>{anime_id}</code>\n🎞 Jami qism: <b>{total}</b>",
        reply_markup=admin_menu_keyboard(),
    )


@router.message(AddAnimeStates.waiting_media, F.text == "❌ Bekor qilish", admin_filter)
async def anime_cancel_text_handler(message: Message, state: FSMContext) -> None:
    track_chat(message.chat, message.from_user)
    data = await state.get_data()
    anime_id = data["anime_id"]
    await cancel_pending_media_group_uploads(anime_id)
    db.delete_anime(anime_id)
    await state.clear()
    await message.answer(
        "❌ Anime qo'shish jarayoni bekor qilindi.",
        reply_markup=admin_menu_keyboard(),
    )


async def wait_pending_media_group_uploads(anime_id: int) -> None:
    while True:
        async with media_group_lock:
            tasks = [
                buffer["task"]
                for buffer in media_group_buffers.values()
                if int(buffer["anime_id"]) == anime_id and "task" in buffer
            ]
        if not tasks:
            return
        await asyncio.gather(*tasks, return_exceptions=True)


async def cancel_pending_media_group_uploads(anime_id: int) -> None:
    async with media_group_lock:
        keys = [
            key
            for key, buffer in media_group_buffers.items()
            if int(buffer["anime_id"]) == anime_id
        ]
        tasks = [
            media_group_buffers[key]["task"]
            for key in keys
            if "task" in media_group_buffers[key]
        ]
        for key in keys:
            media_group_buffers.pop(key, None)

    for task in tasks:
        task.cancel()


async def store_episode_message(message: Message, anime_id: int) -> int | None:
    copied_message = await message.bot.copy_message(
        chat_id=config.storage_channel_id,
        from_chat_id=message.chat.id,
        message_id=message.message_id,
    )
    try:
        return db.add_episode(
            anime_id=anime_id,
            storage_message_id=copied_message.message_id,
            content_type=message.content_type,
        )
    except sqlite3.IntegrityError:
        try:
            await message.bot.delete_message(
                chat_id=config.storage_channel_id,
                message_id=copied_message.message_id,
            )
        except TelegramBadRequest:
            pass
        return None


async def process_media_group_upload(key: tuple[int, str]) -> None:
    await asyncio.sleep(MEDIA_GROUP_COLLECT_DELAY)
    async with media_group_lock:
        buffer = media_group_buffers.pop(key, None)

    if not buffer:
        return

    anime_id = int(buffer["anime_id"])
    messages = sorted(buffer["messages"].values(), key=lambda item: item.message_id)
    saved_episode_numbers: list[int] = []
    async with get_anime_upload_lock(anime_id):
        for media_message in messages:
            episode_number = await store_episode_message(media_message, anime_id)
            if episode_number:
                saved_episode_numbers.append(episode_number)

    notify_message = messages[-1]
    if not saved_episode_numbers:
        await notify_message.answer(
            "⚠️ Qismlar saqlanmadi. Fayllarni ketma-ket yoki 10 tadan bo'lib yuboring."
        )
        return

    if len(saved_episode_numbers) == 1:
        await notify_message.answer(f"✅ {saved_episode_numbers[0]}-qism saqlandi.")
        return

    await notify_message.answer(
        f"✅ {saved_episode_numbers[0]}-{saved_episode_numbers[-1]}-qismlar tartib bilan saqlandi."
    )


@router.message(AddAnimeStates.waiting_media, admin_filter)
async def anime_media_handler(message: Message, state: FSMContext) -> None:
    track_chat(message.chat, message.from_user)
    content_type = message.content_type
    if content_type not in EPISODE_CONTENT_TYPES:
        await message.answer("⚠️ Qism sifatida video, document, audio, voice, photo yoki text yuboring.")
        return

    data = await state.get_data()
    anime_id = int(data["anime_id"])
    if message.media_group_id:
        key = (message.chat.id, message.media_group_id)
        async with media_group_lock:
            buffer = media_group_buffers.get(key)
            if not buffer:
                task = asyncio.create_task(process_media_group_upload(key))
                buffer = {
                    "anime_id": anime_id,
                    "messages": {},
                    "task": task,
                }
                media_group_buffers[key] = buffer
            buffer["messages"][message.message_id] = message
        return

    async with get_anime_upload_lock(anime_id):
        episode_number = await store_episode_message(message, anime_id)
    if not episode_number:
        await message.answer(
            "⚠️ Qism saqlanmadi. Fayllarni ketma-ket yoki 10 tadan bo'lib yuboring."
        )
        return
    await message.answer(f"✅ {episode_number}-qism saqlandi.")


@router.callback_query(F.data.startswith("anime_done:"), admin_filter)
async def anime_done_handler(callback: CallbackQuery, state: FSMContext) -> None:
    anime_id = int(callback.data.split(":")[1])
    await wait_pending_media_group_uploads(anime_id)
    total = db.finalize_anime(anime_id)
    if total == 0:
        db.delete_anime(anime_id)
        await state.clear()
        await callback.answer("⚠️ Hech qanday qism yuklanmadi.", show_alert=True)
        await callback.message.answer("❌ Anime bekor qilindi, chunki qism yo'q.")
        return

    await state.clear()
    await callback.answer("✅ Anime yakunlandi.")
    await callback.message.answer(
        f"✅ Anime saqlandi.\n🆔 ID: <code>{anime_id}</code>\n🎞 Jami qism: <b>{total}</b>",
        reply_markup=admin_menu_keyboard(),
    )


@router.callback_query(F.data.startswith("anime_cancel:"), admin_filter)
async def anime_cancel_handler(callback: CallbackQuery, state: FSMContext) -> None:
    anime_id = int(callback.data.split(":")[1])
    await cancel_pending_media_group_uploads(anime_id)
    db.delete_anime(anime_id)
    await state.clear()
    await callback.answer("❌ Jarayon bekor qilindi.")
    await callback.message.answer(
        "❌ Anime qo'shish jarayoni bekor qilindi.",
        reply_markup=admin_menu_keyboard(),
    )


@router.message(DeleteAnimeStates.waiting_id, admin_filter)
async def delete_anime_by_id_handler(message: Message, state: FSMContext) -> None:
    track_chat(message.chat, message.from_user)
    if not message.text or not message.text.isdigit():
        await message.answer("⚠️ ID faqat raqamdan iborat bo'lishi kerak.")
        return

    anime_id = int(message.text)
    anime = db.get_any_anime(anime_id)
    if not anime:
        await message.answer("❌ Bunday anime topilmadi. Boshqa ID yuboring yoki /admin ni bosing.")
        return

    await delete_anime_assets(message.bot, anime_id)
    db.delete_anime(anime_id)
    await state.clear()
    await message.answer(
        f"✅ Anime o'chirildi.\n🆔 ID: <code>{anime_id}</code>\n🎬 Nomi: <b>{anime['title']}</b>",
        reply_markup=admin_menu_keyboard(),
    )


@router.message(F.text == "📊 Statistika", admin_filter)
async def stats_handler(message: Message) -> None:
    track_chat(message.chat, message.from_user)
    stats = db.get_stats()
    text = (
        "<b>📊 Statistika</b>\n"
        f"👤 Userlar: <b>{stats['total_users']}</b>\n"
        f"🔥 So'nggi 24 soatda aktiv: <b>{stats['active_users']}</b>\n"
        f"👥 Guruh/Kanallar: <b>{stats['total_groups']}</b>\n"
        f"🎬 Animelar: <b>{stats['total_anime']}</b>\n"
        f"🎞 Qismlar: <b>{stats['total_episodes']}</b>\n"
        f"🔐 Majburiy obuna kanallari: <b>{stats['subscription_channels']}</b>"
    )
    await message.answer(text)


@router.message(F.text == "📣 Broadcast", admin_filter)
async def broadcast_menu_handler(message: Message, state: FSMContext) -> None:
    track_chat(message.chat, message.from_user)
    await state.clear()
    await message.answer(
        "📣 Xabar yuboriladigan auditoriyani tanlang.",
        reply_markup=broadcast_target_keyboard(),
    )


@router.callback_query(F.data.startswith("broadcast:"), admin_filter)
async def broadcast_target_handler(callback: CallbackQuery, state: FSMContext) -> None:
    target = callback.data.split(":")[1]
    await state.set_state(BroadcastStates.waiting_message)
    await state.update_data(broadcast_target=target)
    await callback.answer()
    await callback.message.answer(
        "✉️ Endi yuboriladigan xabarni jo'nating.\n"
        "🖼 Text, photo, video, voice, audio, document va boshqa odatiy xabarlar ishlaydi."
    )


@router.message(BroadcastStates.waiting_message, admin_filter)
async def broadcast_send_handler(message: Message, state: FSMContext) -> None:
    track_chat(message.chat, message.from_user)
    data = await state.get_data()
    target = data.get("broadcast_target", "all")
    chat_ids = db.get_broadcast_targets(target)
    success = 0
    failed = 0

    for chat_id in chat_ids:
        try:
            await message.bot.copy_message(
                chat_id=chat_id,
                from_chat_id=message.chat.id,
                message_id=message.message_id,
            )
            success += 1
        except (TelegramBadRequest, TelegramForbiddenError):
            failed += 1
        await asyncio.sleep(0.05)

    await state.clear()
    await message.answer(
        f"✅ Broadcast tugadi.\n📨 Yetkazildi: <b>{success}</b>\n⚠️ Xatolik: <b>{failed}</b>"
    )


@router.message(F.text == "🔐 Majburiy obuna", admin_filter)
async def subscription_menu_handler(message: Message, state: FSMContext) -> None:
    track_chat(message.chat, message.from_user)
    await state.clear()
    total = len(db.get_subscription_channels())
    await message.answer(
        f"🔐 Hozir {total} ta majburiy obuna kanali mavjud.",
        reply_markup=subscription_manage_keyboard(),
    )


@router.callback_query(F.data == "sub_manage:update", admin_filter)
async def subscription_update_handler(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SubscriptionStates.waiting_channels)
    await callback.answer()
    await callback.message.answer(
        "📥 Kanallarni bittadan yangi qatorda yuboring.\n"
        "📎 Format: `@username`, `https://t.me/username` yoki numeric chat ID.\n"
        "⚠️ Private invite link ishlatilmaydi."
    )


@router.callback_query(F.data == "sub_manage:list", admin_filter)
async def subscription_list_handler(callback: CallbackQuery) -> None:
    channels = db.get_subscription_channels()
    if not channels:
        await callback.answer("📭 Ro'yxat bo'sh.", show_alert=True)
        return

    lines = ["<b>🔐 Majburiy obuna kanallari</b>"]
    for index, channel in enumerate(channels, start=1):
        title = channel["title"] or channel["chat_ref"]
        lines.append(f"{index}. {title} - <code>{channel['chat_ref']}</code>")
    await callback.answer()
    await callback.message.answer("\n".join(lines))


@router.callback_query(F.data == "sub_manage:clear", admin_filter)
async def subscription_clear_handler(callback: CallbackQuery, state: FSMContext) -> None:
    db.clear_subscription_channels()
    await state.clear()
    await callback.answer("🗑 Majburiy obuna o'chirildi.")
    await callback.message.answer("🗑 Majburiy obuna kanallari tozalandi.")


@router.message(SubscriptionStates.waiting_channels, admin_filter)
async def subscription_save_handler(message: Message, state: FSMContext) -> None:
    track_chat(message.chat, message.from_user)
    if not message.text:
        await message.answer("⚠️ Kanallar ro'yxatini matn ko'rinishida yuboring.")
        return

    channels: list[dict[str, str | None]] = []
    errors: list[str] = []

    for line in message.text.splitlines():
        if not line.strip():
            continue
        try:
            chat_ref, invite_link = normalize_subscription_input(line)
            chat = await message.bot.get_chat(parse_chat_ref(chat_ref))
            title = chat.title or chat.username or chat_ref
            final_link = invite_link or (f"https://t.me/{chat.username}" if chat.username else None)
            channels.append(
                {
                    "chat_ref": str(chat_ref),
                    "invite_link": final_link,
                    "title": title,
                }
            )
        except (ValueError, TelegramBadRequest) as exc:
            errors.append(f"{line} -> {exc}")

    if errors:
        await message.answer(
            "⚠️ Quyidagi qatorlarda muammo bor:\n" + "\n".join(errors[:10])
        )
        return

    db.replace_subscription_channels(channels)
    await state.clear()
    await message.answer(f"✅ {len(channels)} ta kanal saqlandi.")


@router.callback_query(F.data == "check_subscription")
async def subscription_check_handler(callback: CallbackQuery) -> None:
    if not await ensure_subscription(callback.bot, callback.from_user.id, callback):
        await callback.answer("⚠️ Hali barcha kanallarga obuna bo'linmagan.", show_alert=True)
        return

    await callback.answer("✅ Obuna tasdiqlandi.", show_alert=True)
    await callback.message.answer(f"🎬 Endi {BOT_NAME} uchun anime ID yuborishingiz mumkin.")


@router.callback_query(F.data == "episode:noop")
async def episode_noop_handler(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(F.data.startswith("episode:"))
async def episode_navigation_handler(callback: CallbackQuery) -> None:
    if not await ensure_subscription(callback.bot, callback.from_user.id, callback):
        await callback.answer()
        return

    _, anime_id_raw, episode_raw = callback.data.split(":")
    await callback.answer()
    await send_episode(
        bot=callback.bot,
        chat_id=callback.message.chat.id,
        anime_id=int(anime_id_raw),
        episode_number=int(episode_raw),
    )


@router.message(F.chat.type == "private", F.text.regexp(r"^\d+$"))
async def anime_search_handler(message: Message) -> None:
    track_chat(message.chat, message.from_user)
    if not await ensure_subscription(message.bot, message.from_user.id, message):
        return
    anime_id = int(message.text)
    await send_title_photo(message.bot, message.chat.id, anime_id)
    await send_episode(message.bot, message.chat.id, anime_id, 1)


@router.channel_post()
async def channel_post_handler(message: Message) -> None:
    track_chat(message.chat, None)


@router.message()
async def fallback_handler(message: Message) -> None:
    track_chat(message.chat, message.from_user)
    if message.chat.type != "private":
        return
    await message.answer(f"{BOT_TAG}\n🎬 Anime ID yuboring.")


async def main() -> None:
    db.init()
    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    try:
        me = await bot.me()
    except TelegramUnauthorizedError:
        logging.error(
            "%s tokeni noto'g'ri yoki bekor qilingan. .env ichidagi BOT_TOKEN ni yangilang.",
            BOT_NAME,
        )
        return

    logging.info("%s ishga tushdi: @%s", BOT_NAME, me.username)
    try:
        await dp.start_polling(bot, skip_updates=True)
    except asyncio.CancelledError:
        logging.info("%s polling to'xtatildi.", BOT_NAME)
    finally:
        await bot.session.close()


def run() -> None:
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("%s to'xtatildi.", BOT_NAME)


if __name__ == "__main__":
    run()
