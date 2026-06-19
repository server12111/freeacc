import logging
from typing import Optional

from aiogram import Bot

from bot.constants import EMOJI_TROPHY

logger = logging.getLogger(__name__)


class AccountIssuerService:
    """Used only for purchase-based account issuance. Contest issuance is handled by ContestSchedulerService."""

    def __init__(self, bot: Bot, db, config) -> None:
        self._bot = bot
        self._db = db
        self._config = config

    async def issue(
        self,
        user_tg_id: int,
        user_username: Optional[str],
        contest_id: Optional[int],
        invite_count: int = 0,
    ) -> bool:
        account = await self._db.claim_free_account()
        if account is None:
            await self._notify_admins_pool_empty()
            logger.warning("Account pool is empty — cannot issue to %s", user_tg_id)
            return False

        parts = account.data.split(":", 1)
        phone = parts[0].strip()

        await self._db.record_issued_account(
            pool_id=account.id,
            user_tg_id=user_tg_id,
            user_username=user_username,
            contest_id=contest_id,
        )

        from bot.keyboards.inline import get_code_kb, warmup_bot_kb
        try:
            await self._bot.send_message(
                user_tg_id,
                f"{EMOJI_TROPHY} <b>Готово! Вот твой аккаунт:</b>\n\n"
                f"📱 Номер телефона:\n<code>{phone}</code>\n\n"
                f"Нажми кнопку ниже чтобы получить код входа 👇",
                reply_markup=get_code_kb(account.id),
                parse_mode="HTML",
            )
        except Exception as exc:
            logger.warning("Cannot send account to user %s: %s", user_tg_id, exc)

        # Send warmup bot recommendation
        try:
            display_name = f"@{user_username}" if user_username else "друг"
            await self._bot.send_message(
                user_tg_id,
                f"🔥 <b>{display_name}, важный совет!</b>\n\n"
                f"Свежий Telegram-аккаунт нужно прогреть — иначе есть риск ограничений.\n\n"
                f"Специально для этого у нас есть <b>@SrvnkWarmUpAccBot</b>:\n"
                f"• Автоматический прогрев\n"
                f"• Безопасно и быстро\n"
                f"• Работает в фоне\n\n"
                f"Рекомендуем прогреть аккаунт сразу после получения 👇",
                parse_mode="HTML",
                reply_markup=warmup_bot_kb(),
            )
        except Exception:
            pass

        uname = f"@{user_username}" if user_username else str(user_tg_id)
        try:
            await self._notify_admins(
                f"✅ Аккаунт куплен\n"
                f"Пользователь: {uname} (id: {user_tg_id})\n"
                f"Номер: {phone}"
            )
        except Exception as exc:
            logger.warning("Failed to notify admins: %s", exc)
        await self._db.add_log(
            "account_issued",
            f"user={user_tg_id} pool_id={account.id} phone={phone}",
        )

        # Check low stock after issuance
        free = await self._db.get_free_accounts_count()
        threshold = int(await self._db.get_setting("account_low_stock_alert", "3"))
        if free <= threshold:
            await self._notify_admins(
                f"⚠️ <b>Аккаунты заканчиваются!</b>\n"
                f"Осталось свободных: <b>{free}</b>\n"
                "Добавьте аккаунты через /admin → 📦 Аккаунты"
            )

        logger.info("Account #%s (%s) issued to user %s (purchase)", account.id, phone, user_tg_id)
        return True

    async def _notify_admins(self, text: str) -> None:
        for admin_id in self._config.ADMIN_IDS:
            try:
                await self._bot.send_message(admin_id, text, parse_mode="HTML")
            except Exception as exc:
                logger.warning("Cannot notify admin %s: %s", admin_id, exc)

    async def _notify_admins_pool_empty(self) -> None:
        await self._notify_admins(
            "⚠️ <b>Пул аккаунтов пуст!</b>\n"
            "Пользователь хочет купить аккаунт, но нет свободных.\n"
            "Добавьте аккаунты через /admin → 📦 Аккаунты"
        )
