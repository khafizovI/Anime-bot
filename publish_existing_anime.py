from __future__ import annotations

import argparse
import asyncio
import logging

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramUnauthorizedError

from app.bot import BOT_NAME, config, db, publish_anime_announcement


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)


def get_completed_anime_ids(force: bool) -> list[int]:
    where = "WHERE is_complete = 1 AND title_photo_message_id IS NOT NULL"
    if not force:
        where += " AND announcement_message_id IS NULL"

    rows = db.conn.execute(
        f"""
        SELECT anime_id
        FROM anime
        {where}
        ORDER BY created_at, anime_id
        """
    ).fetchall()
    return [int(row["anime_id"]) for row in rows]


def clear_announcement(anime_id: int) -> None:
    db.conn.execute(
        """
        UPDATE anime
        SET announcement_message_id = NULL
        WHERE anime_id = ?
        """,
        (anime_id,),
    )
    db.conn.commit()


async def publish_existing_anime(force: bool) -> None:
    db.init()
    anime_ids = get_completed_anime_ids(force)
    if not anime_ids:
        logging.info("Kanalga tashlanadigan anime topilmadi.")
        return

    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        me = await bot.me()
    except TelegramUnauthorizedError:
        logging.error("%s tokeni noto'g'ri yoki bekor qilingan.", BOT_NAME)
        await bot.session.close()
        return

    logging.info("%s orqali %s ta anime kanalga tashlanadi: @%s", BOT_NAME, len(anime_ids), me.username)
    published = 0
    failed = 0
    try:
        for anime_id in anime_ids:
            if force:
                clear_announcement(anime_id)

            if await publish_anime_announcement(bot, anime_id):
                published += 1
                logging.info("Tashlandi: anime_id=%s", anime_id)
            else:
                failed += 1
                logging.warning("Tashlanmadi: anime_id=%s", anime_id)

            await asyncio.sleep(0.4)
    finally:
        await bot.session.close()

    logging.info("Tugadi. Tashlandi: %s, xatolik: %s", published, failed)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Eski animelarni announcement kanaliga Tomosha qilish buttoni bilan tashlaydi."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Oldin kanalga tashlangan animelarni ham qayta tashlaydi.",
    )
    args = parser.parse_args()
    asyncio.run(publish_existing_anime(force=args.force))


if __name__ == "__main__":
    main()
