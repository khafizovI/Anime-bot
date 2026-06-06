from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")

    def init(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS chats (
                chat_id INTEGER PRIMARY KEY,
                chat_type TEXT NOT NULL,
                title TEXT,
                username TEXT,
                full_name TEXT,
                last_seen TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS anime (
                anime_id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT,
                status TEXT NOT NULL DEFAULT 'ongoing',
                title_photo_message_id INTEGER,
                episodes_count INTEGER NOT NULL DEFAULT 0,
                is_complete INTEGER NOT NULL DEFAULT 0,
                created_by INTEGER,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS episodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                anime_id INTEGER NOT NULL REFERENCES anime(anime_id) ON DELETE CASCADE,
                episode_number INTEGER NOT NULL,
                storage_message_id INTEGER NOT NULL,
                content_type TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE (anime_id, episode_number)
            );

            CREATE TABLE IF NOT EXISTS subscription_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_ref TEXT NOT NULL,
                invite_link TEXT,
                title TEXT
            );
            """
        )
        self._ensure_anime_columns()
        self.conn.commit()

    def _ensure_anime_columns(self) -> None:
        columns = {
            row["name"]
            for row in self.conn.execute("PRAGMA table_info(anime)").fetchall()
        }
        if "title_photo_message_id" not in columns:
            self.conn.execute(
                "ALTER TABLE anime ADD COLUMN title_photo_message_id INTEGER"
            )
        if "status" not in columns:
            self.conn.execute(
                "ALTER TABLE anime ADD COLUMN status TEXT NOT NULL DEFAULT 'ongoing'"
            )

    def upsert_chat(
        self,
        chat_id: int,
        chat_type: str,
        title: str | None,
        username: str | None,
        full_name: str | None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO chats (chat_id, chat_type, title, username, full_name, last_seen)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                chat_type = excluded.chat_type,
                title = excluded.title,
                username = excluded.username,
                full_name = excluded.full_name,
                last_seen = excluded.last_seen
            """,
            (chat_id, chat_type, title, username, full_name, utc_now_iso()),
        )
        self.conn.commit()

    def create_anime(
        self,
        anime_id: int,
        title: str,
        description: str,
        status: str,
        title_photo_message_id: int | None,
        created_by: int,
    ) -> bool:
        try:
            self.conn.execute(
                """
                INSERT INTO anime (
                    anime_id, title, description, status, title_photo_message_id, created_by, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    anime_id,
                    title,
                    description,
                    status,
                    title_photo_message_id,
                    created_by,
                    utc_now_iso(),
                ),
            )
            self.conn.commit()
        except sqlite3.IntegrityError:
            self.conn.rollback()
            return False
        return True

    def anime_exists(self, anime_id: int) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM anime WHERE anime_id = ?",
            (anime_id,),
        ).fetchone()
        return row is not None

    def get_anime(self, anime_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            """
            SELECT
                anime_id,
                title,
                description,
                status,
                title_photo_message_id,
                episodes_count,
                is_complete,
                created_by,
                created_at
            FROM anime
            WHERE anime_id = ? AND is_complete = 1
            """,
            (anime_id,),
        ).fetchone()

    def get_any_anime(self, anime_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM anime WHERE anime_id = ?",
            (anime_id,),
        ).fetchone()

    def get_anime_storage_message_ids(self, anime_id: int) -> list[int]:
        message_ids: list[int] = []
        anime = self.get_any_anime(anime_id)
        if anime and anime["title_photo_message_id"]:
            message_ids.append(int(anime["title_photo_message_id"]))

        rows = self.conn.execute(
            """
            SELECT storage_message_id
            FROM episodes
            WHERE anime_id = ?
            ORDER BY episode_number
            """,
            (anime_id,),
        ).fetchall()
        message_ids.extend(int(row["storage_message_id"]) for row in rows)
        return message_ids

    def delete_anime(self, anime_id: int) -> None:
        self.conn.execute("DELETE FROM anime WHERE anime_id = ?", (anime_id,))
        self.conn.commit()

    def finalize_anime(self, anime_id: int) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS total FROM episodes WHERE anime_id = ?",
            (anime_id,),
        ).fetchone()
        total = int(row["total"])
        self.conn.execute(
            """
            UPDATE anime
            SET episodes_count = ?, is_complete = 1
            WHERE anime_id = ?
            """,
            (total, anime_id),
        )
        self.conn.commit()
        return total

    def add_episode(
        self,
        anime_id: int,
        storage_message_id: int,
        content_type: str,
    ) -> int:
        for _ in range(3):
            try:
                self.conn.execute("BEGIN IMMEDIATE")
                row = self.conn.execute(
                    """
                    SELECT COALESCE(MAX(episode_number), 0) + 1 AS next_episode
                    FROM episodes
                    WHERE anime_id = ?
                    """,
                    (anime_id,),
                ).fetchone()
                next_episode = int(row["next_episode"])
                self.conn.execute(
                    """
                    INSERT INTO episodes (
                        anime_id, episode_number, storage_message_id, content_type, created_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        anime_id,
                        next_episode,
                        storage_message_id,
                        content_type,
                        utc_now_iso(),
                    ),
                )
                self.conn.commit()
                return next_episode
            except sqlite3.IntegrityError:
                self.conn.rollback()

        raise sqlite3.IntegrityError("Episode number conflict")

    def get_episode_count(self, anime_id: int) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS total FROM episodes WHERE anime_id = ?",
            (anime_id,),
        ).fetchone()
        return int(row["total"])

    def get_total_episodes(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) AS total FROM episodes").fetchone()
        return int(row["total"])

    def get_episode(self, anime_id: int, episode_number: int) -> sqlite3.Row | None:
        return self.conn.execute(
            """
            SELECT anime_id, episode_number, storage_message_id, content_type
            FROM episodes
            WHERE anime_id = ? AND episode_number = ?
            """,
            (anime_id, episode_number),
        ).fetchone()

    def get_subscription_channels(self) -> list[sqlite3.Row]:
        rows = self.conn.execute(
            """
            SELECT id, chat_ref, invite_link, title
            FROM subscription_channels
            ORDER BY id
            """
        ).fetchall()
        return list(rows)

    def replace_subscription_channels(self, channels: list[dict[str, str | None]]) -> None:
        self.conn.execute("DELETE FROM subscription_channels")
        self.conn.executemany(
            """
            INSERT INTO subscription_channels (chat_ref, invite_link, title)
            VALUES (?, ?, ?)
            """,
            [
                (channel["chat_ref"], channel["invite_link"], channel["title"])
                for channel in channels
            ],
        )
        self.conn.commit()

    def clear_subscription_channels(self) -> None:
        self.conn.execute("DELETE FROM subscription_channels")
        self.conn.commit()

    def get_stats(self) -> dict[str, Any]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        total_users = self.conn.execute(
            "SELECT COUNT(*) AS total FROM chats WHERE chat_type = 'private'"
        ).fetchone()["total"]
        active_users = self.conn.execute(
            """
            SELECT COUNT(*) AS total
            FROM chats
            WHERE chat_type = 'private' AND last_seen >= ?
            """,
            (cutoff,),
        ).fetchone()["total"]
        total_groups = self.conn.execute(
            """
            SELECT COUNT(*) AS total
            FROM chats
            WHERE chat_type IN ('group', 'supergroup', 'channel')
            """
        ).fetchone()["total"]
        total_anime = self.conn.execute(
            "SELECT COUNT(*) AS total FROM anime WHERE is_complete = 1"
        ).fetchone()["total"]
        total_subs = self.conn.execute(
            "SELECT COUNT(*) AS total FROM subscription_channels"
        ).fetchone()["total"]
        return {
            "total_users": int(total_users),
            "active_users": int(active_users),
            "total_groups": int(total_groups),
            "total_anime": int(total_anime),
            "total_episodes": self.get_total_episodes(),
            "subscription_channels": int(total_subs),
        }

    def get_broadcast_targets(self, target: str) -> list[int]:
        if target == "users":
            query = "SELECT chat_id FROM chats WHERE chat_type = 'private'"
        elif target == "groups":
            query = "SELECT chat_id FROM chats WHERE chat_type IN ('group', 'supergroup', 'channel')"
        else:
            query = "SELECT chat_id FROM chats"
        rows = self.conn.execute(query).fetchall()
        return [int(row["chat_id"]) for row in rows]
