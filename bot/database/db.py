import logging
import aiosqlite
from typing import Optional
from .models import (
    SCHEMA, User, AccountPool, Contest, IssuedAccount,
    Purchase, Referral, PromoCode, ReferralReward, AdsItem,
)

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, path: str) -> None:
        self._path = path
        self._conn: Optional[aiosqlite.Connection] = None

    async def init(self) -> None:
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA foreign_keys = ON")
        await self._conn.execute("PRAGMA journal_mode = WAL")
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()
        for migration in (
            "ALTER TABLE contests ADD COLUMN launched_at DATETIME",
            "ALTER TABLE contests ADD COLUMN milestone_10 INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE contests ADD COLUMN milestone_20 INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE contests ADD COLUMN milestone_30 INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE contests ADD COLUMN invite_count_offset INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE ads_items ADD COLUMN text TEXT NOT NULL DEFAULT ''",
            "UPDATE ads_items SET text = url WHERE text = ''",
        ):
            try:
                await self._conn.execute(migration)
                await self._conn.commit()
            except Exception as exc:
                if "duplicate column name" not in str(exc).lower():
                    logger.warning("Migration skipped (%s): %s", migration[:60], exc)

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()

    # ── Users ──────────────────────────────────────────────────────────────

    async def get_or_create_user(
        self, tg_id: int, username: Optional[str], first_name: Optional[str]
    ) -> tuple[User, bool]:
        async with self._conn.execute(
            "SELECT * FROM users WHERE tg_id = ?", (tg_id,)
        ) as cur:
            row = await cur.fetchone()
        if row:
            return User(**dict(row)), False
        await self._conn.execute(
            "INSERT INTO users (tg_id, username, first_name) VALUES (?, ?, ?)",
            (tg_id, username, first_name),
        )
        await self._conn.commit()
        async with self._conn.execute(
            "SELECT * FROM users WHERE tg_id = ?", (tg_id,)
        ) as cur:
            row = await cur.fetchone()
        return User(**dict(row)), True

    async def get_all_users(self) -> list[User]:
        async with self._conn.execute("SELECT * FROM users ORDER BY id") as cur:
            return [User(**dict(r)) for r in await cur.fetchall()]

    async def get_user_by_tg_id(self, tg_id: int) -> Optional[User]:
        async with self._conn.execute(
            "SELECT * FROM users WHERE tg_id = ?", (tg_id,)
        ) as cur:
            row = await cur.fetchone()
            return User(**dict(row)) if row else None

    # ── Accounts pool ──────────────────────────────────────────────────────

    async def add_accounts(self, data_list: list[str], added_by: int) -> int:
        rows = [(d, added_by) for d in data_list]
        await self._conn.executemany(
            "INSERT INTO accounts_pool (data, added_by) VALUES (?, ?)", rows
        )
        await self._conn.commit()
        return len(rows)

    async def get_account_by_id(self, pool_id: int) -> Optional[AccountPool]:
        async with self._conn.execute(
            "SELECT * FROM accounts_pool WHERE id = ?", (pool_id,)
        ) as cur:
            row = await cur.fetchone()
            return AccountPool(**dict(row)) if row else None

    async def get_free_accounts_count(self) -> int:
        async with self._conn.execute(
            "SELECT COUNT(*) FROM accounts_pool WHERE status = 'free'"
        ) as cur:
            return (await cur.fetchone())[0]

    async def get_issued_accounts_count(self) -> int:
        async with self._conn.execute(
            "SELECT COUNT(*) FROM accounts_pool WHERE status = 'issued'"
        ) as cur:
            return (await cur.fetchone())[0]

    async def get_issued_history(self, limit: int = 20) -> list[IssuedAccount]:
        async with self._conn.execute(
            "SELECT * FROM issued_accounts ORDER BY issued_at DESC LIMIT ?", (limit,)
        ) as cur:
            return [IssuedAccount(**dict(r)) for r in await cur.fetchall()]

    async def claim_free_account(self) -> Optional[AccountPool]:
        async with self._conn.execute(
            """UPDATE accounts_pool SET status = 'issued'
               WHERE id = (
                   SELECT id FROM accounts_pool WHERE status = 'free' ORDER BY id LIMIT 1
               )
               RETURNING id, data, status, added_by, added_at"""
        ) as cur:
            row = await cur.fetchone()
        await self._conn.commit()
        return AccountPool(**dict(row)) if row else None

    async def record_issued_account(
        self,
        pool_id: int,
        user_tg_id: int,
        user_username: Optional[str],
        contest_id: Optional[int],
    ) -> None:
        await self._conn.execute(
            "INSERT INTO issued_accounts (pool_id, user_tg_id, user_username, contest_id)"
            " VALUES (?, ?, ?, ?)",
            (pool_id, user_tg_id, user_username, contest_id),
        )
        await self._conn.commit()

    async def is_account_recipient(self, tg_id: int) -> bool:
        async with self._conn.execute(
            "SELECT 1 FROM issued_accounts WHERE user_tg_id = ? LIMIT 1", (tg_id,)
        ) as cur:
            return await cur.fetchone() is not None

    # ── Contests ───────────────────────────────────────────────────────────

    async def get_next_participant_number(self) -> int:
        async with self._conn.execute("SELECT COUNT(*) FROM contests") as cur:
            return (await cur.fetchone())[0] + 1

    async def create_contest(
        self,
        owner_tg_id: int,
        channel_id: str,
        threshold: int,
        participant_number: int,
        status: str = "pending",
    ) -> Contest:
        await self._conn.execute(
            "INSERT INTO contests"
            " (owner_tg_id, channel_id, invite_threshold, participant_number, status)"
            " VALUES (?, ?, ?, ?, ?)",
            (owner_tg_id, channel_id, threshold, participant_number, status),
        )
        await self._conn.commit()
        async with self._conn.execute(
            "SELECT * FROM contests ORDER BY id DESC LIMIT 1"
        ) as cur:
            return Contest(**dict(await cur.fetchone()))

    async def set_contest_piarflow(
        self, contest_id: int, msg_id: Optional[int], link: Optional[str]
    ) -> None:
        await self._conn.execute(
            "UPDATE contests SET piarflow_msg_id = ?, piarflow_link = ?,"
            " status = 'active', launched_at = CURRENT_TIMESTAMP WHERE id = ?",
            (msg_id, link, contest_id),
        )
        await self._conn.commit()

    async def update_contest_invite_count(self, contest_id: int, count: int) -> Contest:
        await self._conn.execute(
            "UPDATE contests SET invite_count = ? WHERE id = ?", (count, contest_id)
        )
        await self._conn.commit()
        async with self._conn.execute(
            "SELECT * FROM contests WHERE id = ?", (contest_id,)
        ) as cur:
            return Contest(**dict(await cur.fetchone()))

    async def mark_contest_account_issued(self, contest_id: int) -> None:
        await self._conn.execute(
            "UPDATE contests SET status = 'finished', finished_at = CURRENT_TIMESTAMP"
            " WHERE id = ?",
            (contest_id,),
        )
        await self._conn.commit()

    async def set_contest_participant_number(self, contest_id: int, num: int) -> None:
        await self._conn.execute(
            "UPDATE contests SET participant_number = ? WHERE id = ?", (num, contest_id)
        )
        await self._conn.commit()

    async def set_contest_invite_offset(self, contest_id: int, offset: int) -> None:
        await self._conn.execute(
            "UPDATE contests SET invite_count_offset = ? WHERE id = ?", (offset, contest_id)
        )
        await self._conn.commit()

    async def set_contest_milestone(self, contest_id: int, milestone: int) -> None:
        col = f"milestone_{milestone}"
        await self._conn.execute(
            f"UPDATE contests SET {col} = 1 WHERE id = ?", (contest_id,)
        )
        await self._conn.commit()

    async def get_active_contests(self) -> list[Contest]:
        async with self._conn.execute(
            "SELECT * FROM contests WHERE status = 'active' ORDER BY id"
        ) as cur:
            return [Contest(**dict(r)) for r in await cur.fetchall()]

    async def get_pending_contests(self) -> list[Contest]:
        async with self._conn.execute(
            "SELECT * FROM contests WHERE status = 'pending' ORDER BY id"
        ) as cur:
            return [Contest(**dict(r)) for r in await cur.fetchall()]

    async def get_all_contests(self) -> list[Contest]:
        async with self._conn.execute(
            "SELECT * FROM contests ORDER BY id DESC"
        ) as cur:
            return [Contest(**dict(r)) for r in await cur.fetchall()]

    async def get_contest(self, contest_id: int) -> Optional[Contest]:
        async with self._conn.execute(
            "SELECT * FROM contests WHERE id = ?", (contest_id,)
        ) as cur:
            row = await cur.fetchone()
            return Contest(**dict(row)) if row else None

    async def get_user_active_contest(self, user_tg_id: int) -> Optional[Contest]:
        async with self._conn.execute(
            "SELECT * FROM contests WHERE owner_tg_id = ? AND status = 'active' LIMIT 1",
            (user_tg_id,),
        ) as cur:
            row = await cur.fetchone()
            return Contest(**dict(row)) if row else None

    async def get_user_current_contest(self, user_tg_id: int) -> Optional[Contest]:
        async with self._conn.execute(
            "SELECT * FROM contests WHERE owner_tg_id = ?"
            " AND status IN ('pending', 'active') ORDER BY id DESC LIMIT 1",
            (user_tg_id,),
        ) as cur:
            row = await cur.fetchone()
            return Contest(**dict(row)) if row else None

    async def get_user_last_contest(self, user_tg_id: int) -> Optional[Contest]:
        async with self._conn.execute(
            "SELECT * FROM contests WHERE owner_tg_id = ? ORDER BY id DESC LIMIT 1",
            (user_tg_id,),
        ) as cur:
            row = await cur.fetchone()
            return Contest(**dict(row)) if row else None

    async def get_contest_by_piarflow_msg(self, msg_id: int) -> Optional[Contest]:
        async with self._conn.execute(
            "SELECT * FROM contests WHERE piarflow_msg_id = ? AND status = 'active'",
            (msg_id,),
        ) as cur:
            row = await cur.fetchone()
            return Contest(**dict(row)) if row else None

    async def get_contest_by_participant_number(self, num: int) -> Optional[Contest]:
        async with self._conn.execute(
            "SELECT * FROM contests WHERE participant_number = ? AND status = 'active'",
            (num,),
        ) as cur:
            row = await cur.fetchone()
            return Contest(**dict(row)) if row else None

    async def set_contest_status(self, contest_id: int, status: str) -> None:
        await self._conn.execute(
            "UPDATE contests SET status = ?,"
            " finished_at = CASE WHEN ? IN ('finished', 'expired') THEN CURRENT_TIMESTAMP ELSE NULL END"
            " WHERE id = ?",
            (status, status, contest_id),
        )
        await self._conn.commit()

    # ── Purchases ──────────────────────────────────────────────────────────

    async def create_purchase(self, user_tg_id: int, invoice_id: str, amount: str) -> Purchase:
        await self._conn.execute(
            "INSERT INTO purchases (user_tg_id, invoice_id, amount) VALUES (?, ?, ?)",
            (user_tg_id, invoice_id, amount),
        )
        await self._conn.commit()
        async with self._conn.execute(
            "SELECT * FROM purchases WHERE invoice_id = ?", (invoice_id,)
        ) as cur:
            return Purchase(**dict(await cur.fetchone()))

    async def get_purchase_by_invoice(self, invoice_id: str) -> Optional[Purchase]:
        async with self._conn.execute(
            "SELECT * FROM purchases WHERE invoice_id = ?", (invoice_id,)
        ) as cur:
            row = await cur.fetchone()
            return Purchase(**dict(row)) if row else None

    async def get_pending_purchase(self, user_tg_id: int) -> Optional[Purchase]:
        async with self._conn.execute(
            "SELECT * FROM purchases WHERE user_tg_id = ? AND status = 'pending' ORDER BY id DESC LIMIT 1",
            (user_tg_id,),
        ) as cur:
            row = await cur.fetchone()
            return Purchase(**dict(row)) if row else None

    async def mark_purchase_paid(self, invoice_id: str, pool_id: int) -> None:
        await self._conn.execute(
            "UPDATE purchases SET status = 'paid', pool_id = ?, paid_at = CURRENT_TIMESTAMP"
            " WHERE invoice_id = ?",
            (pool_id, invoice_id),
        )
        await self._conn.commit()

    async def cancel_pending_purchases(self, user_tg_id: int) -> None:
        await self._conn.execute(
            "UPDATE purchases SET status = 'cancelled' WHERE user_tg_id = ? AND status = 'pending'",
            (user_tg_id,),
        )
        await self._conn.commit()

    # ── Referrals ──────────────────────────────────────────────────────────

    async def get_referral_by_referee(self, referee_tg_id: int) -> Optional[Referral]:
        async with self._conn.execute(
            "SELECT * FROM referrals WHERE referee_tg_id = ?", (referee_tg_id,)
        ) as cur:
            row = await cur.fetchone()
            return Referral(**dict(row)) if row else None

    async def create_referral(self, referrer_tg_id: int, referee_tg_id: int) -> None:
        try:
            await self._conn.execute(
                "INSERT OR IGNORE INTO referrals (referrer_tg_id, referee_tg_id) VALUES (?, ?)",
                (referrer_tg_id, referee_tg_id),
            )
            await self._conn.commit()
        except Exception:
            pass

    async def mark_referral_won(self, referee_tg_id: int) -> None:
        await self._conn.execute(
            "UPDATE referrals SET won = 1 WHERE referee_tg_id = ?", (referee_tg_id,)
        )
        await self._conn.commit()

    async def count_won_referrals(self, referrer_tg_id: int) -> int:
        async with self._conn.execute(
            "SELECT COUNT(*) FROM referrals WHERE referrer_tg_id = ? AND won = 1",
            (referrer_tg_id,),
        ) as cur:
            return (await cur.fetchone())[0]

    async def count_all_referrals(self, referrer_tg_id: int) -> int:
        async with self._conn.execute(
            "SELECT COUNT(*) FROM referrals WHERE referrer_tg_id = ?",
            (referrer_tg_id,),
        ) as cur:
            return (await cur.fetchone())[0]

    async def has_referral_reward(self, user_tg_id: int) -> bool:
        async with self._conn.execute(
            "SELECT 1 FROM referral_rewards WHERE user_tg_id = ? LIMIT 1", (user_tg_id,)
        ) as cur:
            return await cur.fetchone() is not None

    async def create_referral_reward(self, user_tg_id: int, pool_id: Optional[int]) -> None:
        await self._conn.execute(
            "INSERT OR IGNORE INTO referral_rewards (user_tg_id, pool_id) VALUES (?, ?)",
            (user_tg_id, pool_id),
        )
        await self._conn.commit()

    # ── Promo codes ────────────────────────────────────────────────────────

    async def add_promo_codes(self, codes: list[str], added_by: int) -> int:
        added = 0
        for code in codes:
            try:
                await self._conn.execute(
                    "INSERT OR IGNORE INTO promo_codes (code, added_by) VALUES (?, ?)",
                    (code, added_by),
                )
                added += 1
            except Exception:
                pass
        await self._conn.commit()
        return added

    async def claim_free_promo(self) -> Optional[PromoCode]:
        async with self._conn.execute(
            """UPDATE promo_codes SET status = 'issued', issued_at = CURRENT_TIMESTAMP
               WHERE id = (
                   SELECT id FROM promo_codes WHERE status = 'free' ORDER BY id LIMIT 1
               )
               RETURNING *"""
        ) as cur:
            row = await cur.fetchone()
        await self._conn.commit()
        return PromoCode(**dict(row)) if row else None

    async def mark_promo_issued_to(self, promo_id: int, user_tg_id: int) -> None:
        await self._conn.execute(
            "UPDATE promo_codes SET issued_to = ? WHERE id = ?", (user_tg_id, promo_id)
        )
        await self._conn.commit()

    async def get_free_promo_count(self) -> int:
        async with self._conn.execute(
            "SELECT COUNT(*) FROM promo_codes WHERE status = 'free'"
        ) as cur:
            return (await cur.fetchone())[0]

    async def get_all_promos(self, limit: int = 50) -> list[PromoCode]:
        async with self._conn.execute(
            "SELECT * FROM promo_codes ORDER BY id DESC LIMIT ?", (limit,)
        ) as cur:
            return [PromoCode(**dict(r)) for r in await cur.fetchall()]

    # ── Settings ───────────────────────────────────────────────────────────

    async def get_setting(self, key: str, default: str = "") -> str:
        async with self._conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else default

    async def set_setting(self, key: str, value: str) -> None:
        await self._conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        await self._conn.commit()

    # ── Ads items ──────────────────────────────────────────────────────────

    async def get_ads_items(self, type: str = None) -> list[AdsItem]:
        if type:
            async with self._conn.execute(
                "SELECT id, type, name, text, created_at FROM ads_items WHERE type = ? ORDER BY id", (type,)
            ) as cur:
                return [AdsItem(**dict(r)) for r in await cur.fetchall()]
        async with self._conn.execute(
            "SELECT id, type, name, text, created_at FROM ads_items ORDER BY id"
        ) as cur:
            return [AdsItem(**dict(r)) for r in await cur.fetchall()]

    async def get_ads_item(self, item_id: int):
        async with self._conn.execute(
            "SELECT id, type, name, text, created_at FROM ads_items WHERE id = ?", (item_id,)
        ) as cur:
            r = await cur.fetchone()
            return AdsItem(**dict(r)) if r else None

    async def add_ads_item(self, type: str, name: str, text: str) -> AdsItem:
        await self._conn.execute(
            "INSERT INTO ads_items (type, name, text) VALUES (?, ?, ?)", (type, name, text)
        )
        await self._conn.commit()
        async with self._conn.execute(
            "SELECT id, type, name, text, created_at FROM ads_items ORDER BY id DESC LIMIT 1"
        ) as cur:
            return AdsItem(**dict(await cur.fetchone()))

    async def delete_ads_item(self, item_id: int) -> None:
        await self._conn.execute("DELETE FROM ads_items WHERE id = ?", (item_id,))
        await self._conn.commit()

    # ── Admin logs ─────────────────────────────────────────────────────────

    async def add_log(
        self, action: str, details: Optional[str] = None, admin_tg_id: Optional[int] = None
    ) -> None:
        await self._conn.execute(
            "INSERT INTO admin_logs (action, details, admin_tg_id) VALUES (?, ?, ?)",
            (action, details, admin_tg_id),
        )
        await self._conn.commit()

    async def get_logs(self, limit: int = 30) -> list[dict]:
        async with self._conn.execute(
            "SELECT * FROM admin_logs ORDER BY created_at DESC LIMIT ?", (limit,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]
