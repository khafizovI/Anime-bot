from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _parse_int_list(value: str) -> set[int]:
    result: set[int] = set()
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        result.add(int(item))
    return result


def parse_chat_ref(value: str) -> int | str:
    value = value.strip()
    if value.lstrip("-").isdigit():
        return int(value)
    return value


@dataclass(slots=True)
class Config:
    bot_token: str
    admin_ids: set[int]
    storage_channel_id: int | str
    database_path: Path


def load_config() -> Config:
    load_dotenv()

    base_dir = Path(__file__).resolve().parent.parent
    bot_token = os.getenv("BOT_TOKEN", "").strip()
    admin_ids_raw = os.getenv("ADMIN_IDS", "").strip()
    storage_channel_raw = os.getenv("STORAGE_CHANNEL_ID", "").strip()
    database_path = Path(os.getenv("DATABASE_PATH", "bot.db"))
    if not database_path.is_absolute():
        database_path = base_dir / database_path

    if not bot_token:
        raise RuntimeError("BOT_TOKEN .env faylida ko'rsatilmagan.")
    if not admin_ids_raw:
        raise RuntimeError("ADMIN_IDS .env faylida ko'rsatilmagan.")
    if not storage_channel_raw:
        raise RuntimeError("STORAGE_CHANNEL_ID .env faylida ko'rsatilmagan.")

    return Config(
        bot_token=bot_token,
        admin_ids=_parse_int_list(admin_ids_raw),
        storage_channel_id=parse_chat_ref(storage_channel_raw),
        database_path=database_path,
    )
