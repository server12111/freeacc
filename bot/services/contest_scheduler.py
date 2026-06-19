import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Optional
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from aiogram import Bot
    from bot.database.db import Database
    from bot.config import Config
    from bot.userbot.manager import UserbotManager

from bot.keyboards.inline import warmup_bot_kb, back_to_menu_kb
from bot.constants import E_CHECK, E_CROSS, E_LOADING, EMOJI_CONFETTI, E_LINK, E_UNLOCK, EMOJI_TROPHY

logger = logging.getLogger(__name__)

KYIV = ZoneInfo("Europe/Kyiv")

TIER_10_TEXT = "🎉 <b>1 аккаунт</b>"
TIER_20_TEXT = "🎉 <b>1 аккаунт + промокод @feAutoSenderbot</b>"
TIER_30_TEXT = "🎉 <b>2 аккаунта + промокод @feAutoSenderbot</b>"


class ContestSchedulerService:
    def __init__(self, bot: "Bot", db: "Database", config: "Config", manager: "UserbotManager") -> None:
        self._bot = bot
        self._db = db
        self._config = config
        self._manager = manager
        self._task: Optional[asyncio.Task] = None
        self._last_launch_date: Optional[str] = None
        self._last_close_date: Optional[str] = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())
        logger.info("ContestSchedulerService started")

    def stop(self) -> None:
        if self._task:
            self._task.cancel()
        logger.info("ContestSchedulerService stopped")

    async def _loop(self) -> None:
        self._last_launch_date = await self._db.get_setting("scheduler_last_launch_date", "")
        self._last_close_date = await self._db.get_setting("scheduler_last_close_date", "")
        while True:
            await asyncio.sleep(60)
            try:
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("ContestScheduler tick error")

    async def _tick(self) -> None:
        now = datetime.now(KYIV)
        today = now.strftime("%Y-%m-%d")

        # Sync from DB every tick so admin time/date changes take effect without restart
        self._last_launch_date = await self._db.get_setting("scheduler_last_launch_date", "")
        self._last_close_date = await self._db.get_setting("scheduler_last_close_date", "")

        start_str = await self._db.get_setting("contest_start_time", "")
        end_str = await self._db.get_setting("contest_end_time", "")

        if start_str and self._should_fire(now, start_str, today, "launch"):
            self._last_launch_date = today
            await self._db.set_setting("scheduler_last_launch_date", today)
            await self._launch_all_pending()

        if end_str and self._should_fire(now, end_str, today, "close"):
            self._last_close_date = today
            await self._db.set_setting("scheduler_last_close_date", today)
            await self._close_all_active()

    def _should_fire(self, now: datetime, time_str: str, today: str, key: str) -> bool:
        try:
            h, m = (int(x) for x in time_str.split(":"))
        except Exception:
            return False
        last = self._last_launch_date if key == "launch" else self._last_close_date
        if last == today:
            return False
        # Fire only within 2 minutes of the scheduled time — no catch-up on late restarts
        now_total = now.hour * 60 + now.minute
        scheduled_total = h * 60 + m
        return 0 <= now_total - scheduled_total <= 1

    async def _notify_admins(self, text: str) -> None:
        for admin_id in self._config.ADMIN_IDS:
            try:
                await self._bot.send_message(admin_id, text, parse_mode="HTML")
            except Exception:
                pass

    async def _check_low_stock(self) -> None:
        acc_count = await self._db.get_free_accounts_count()
        acc_threshold = int(await self._db.get_setting("account_low_stock_alert", "3"))
        if acc_count <= acc_threshold:
            await self._notify_admins(
                f"⚠️ <b>Аккаунты заканчиваются!</b>\n"
                f"Осталось свободных: <b>{acc_count}</b>\n"
                "Добавьте аккаунты через /admin → 📦 Аккаунты"
            )

        promo_count = await self._db.get_free_promo_count()
        promo_threshold = int(await self._db.get_setting("promo_low_stock_alert", "5"))
        if promo_count <= promo_threshold:
            await self._notify_admins(
                f"⚠️ <b>Промокоды заканчиваются!</b>\n"
                f"Осталось свободных: <b>{promo_count}</b>\n"
                "Добавьте промокоды через /admin → 🎟 Промокоды"
            )

    async def _get_username_text(self, tg_id: int) -> str:
        user = await self._db.get_user_by_tg_id(tg_id)
        if user:
            if user.username:
                return f"@{user.username}"
            if user.first_name:
                return user.first_name
        return str(tg_id)

    # ── Launch pending contests ────────────────────────────────────────────

    async def _launch_all_pending(self) -> None:
        pending = await self._db.get_pending_contests()
        if not pending:
            logger.info("Scheduler: no pending contests to launch")
            return

        logger.info("Scheduler: launching %d pending contests", len(pending))

        for i, contest in enumerate(pending, start=1):
            await self._db.set_contest_participant_number(contest.id, i)
            contest.participant_number = i

        for contest in pending:
            try:
                await self._launch_one(contest)
            except Exception:
                logger.exception("Scheduler: failed to launch contest #%d", contest.id)
            await asyncio.sleep(5)

    async def _launch_one(self, contest) -> None:
        try:
            await self._bot.send_message(
                contest.owner_tg_id,
                f"{E_LOADING} <b>Запускаем твой конкурс...</b>\n\nЖди — это займёт ~1 минуту 🔄",
                parse_mode="HTML",
            )
        except Exception:
            pass

        if not self._manager.is_connected:
            logger.warning("Scheduler: userbot not connected, skipping contest #%d", contest.id)
            return

        username_text = await self._get_username_text(contest.owner_tg_id)

        link = await self._manager.create_piarflow_contest(
            contest_id=contest.id,
            participant_number=contest.participant_number,
            username_text=username_text,
            db=self._db,
            status_message=None,
        )

        if link:
            try:
                await self._bot.send_message(
                    contest.owner_tg_id,
                    f"{EMOJI_CONFETTI} <b>Конкурс запущен!</b>\n\n"
                    f"{E_LINK} <b>Твоя ссылка:</b>\n<a href=\"{link}\">{link}</a>\n\n"
                    f"Скидывай ссылку друзьям и собирай участников! 💪",
                    parse_mode="HTML",
                )
            except Exception:
                pass
            logger.info("Scheduler: contest #%d launched, link=%s", contest.id, link)
        else:
            logger.error("Scheduler: PiarFlowBot failed for contest #%d", contest.id)

    # ── Close active contests + issue rewards ─────────────────────────────

    async def _close_all_active(self) -> None:
        active = await self._db.get_active_contests()
        if not active:
            logger.info("Scheduler: no active contests to close")
            return

        logger.info("Scheduler: closing %d active contests", len(active))

        for contest in active:
            try:
                await self._close_one(contest)
            except Exception:
                logger.exception("Scheduler: failed to close contest #%d", contest.id)
            await asyncio.sleep(1)

    async def _close_one(self, contest) -> None:
        count = contest.invite_count
        tier = 30 if count >= 30 else (20 if count >= 20 else (10 if count >= 10 else 0))

        if tier >= 10:
            await self._issue_tier_rewards(contest, tier)
            await self._db.set_contest_status(contest.id, "finished")
            await self._handle_referral_win(contest.owner_tg_id)
        else:
            await self._db.set_contest_status(contest.id, "expired")
            try:
                await self._bot.send_message(
                    contest.owner_tg_id,
                    f"{E_CROSS} <b>Конкурс завершился</b>\n\n"
                    f"К сожалению, не удалось набрать 10 участников "
                    f"({count} / 10).\n\n"
                    f"Возвращайся завтра — сможешь зарегистрироваться снова! 💪",
                    parse_mode="HTML",
                    reply_markup=back_to_menu_kb(),
                )
            except Exception:
                pass

        logger.info("Scheduler: contest #%d closed (count=%d, tier=%d)", contest.id, count, tier)

    async def _issue_tier_rewards(self, contest, tier: int) -> None:
        user_tg_id = contest.owner_tg_id
        contest_id = contest.id
        count = contest.invite_count
        user = await self._db.get_user_by_tg_id(user_tg_id)
        user_username = user.username if user else None
        display_name = f"@{user_username}" if user_username else (user.first_name if user and user.first_name else "друг")

        tier_label = TIER_30_TEXT if tier >= 30 else (TIER_20_TEXT if tier >= 20 else TIER_10_TEXT)

        # Issue first account (all tiers)
        account1 = await self._db.claim_free_account()
        if account1:
            parts = account1.data.split(":", 1)
            phone1 = parts[0].strip()
            await self._db.record_issued_account(account1.id, user_tg_id, user_username, contest_id)
            try:
                from bot.keyboards.inline import get_code_kb
                await self._bot.send_message(
                    user_tg_id,
                    f"{EMOJI_TROPHY} <b>Поздравляем! Ты выиграл конкурс!</b>\n\n"
                    f"Участников собрано: <b>{count}</b>\n"
                    f"Награда: {tier_label}\n\n"
                    f"📱 <b>Аккаунт #1:</b>\n"
                    f"Номер телефона: <code>{phone1}</code>\n\n"
                    f"Нажми кнопку ниже чтобы получить код входа 👇",
                    parse_mode="HTML",
                    reply_markup=get_code_kb(account1.id),
                )
            except Exception:
                pass
            await self._check_low_stock()

        # Issue promo code (tier 20+)
        if tier >= 20:
            promo = await self._db.claim_free_promo()
            if promo:
                await self._db.mark_promo_issued_to(promo.id, user_tg_id)
                try:
                    await self._bot.send_message(
                        user_tg_id,
                        f"🎟 <b>Твой промокод для @feAutoSenderbot:</b>\n\n"
                        f"<code>{promo.code}</code>\n\n"
                        f"Вводи в боте @feAutoSenderbot для активации <b>2 дней рассылки</b>!\n"
                        f"👉 https://t.me/feAutoSenderbot",
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
                await self._check_low_stock()
            else:
                await self._notify_admins(
                    f"⚠️ <b>Промокоды закончились!</b>\n"
                    f"Пользователь {user_tg_id} выиграл тир {tier}, но промокодов нет.\n"
                    "Добавьте промокоды через /admin → 🎟 Промокоды"
                )

        # Issue second account (tier 30)
        if tier >= 30:
            account2 = await self._db.claim_free_account()
            if account2:
                parts2 = account2.data.split(":", 1)
                phone2 = parts2[0].strip()
                await self._db.record_issued_account(account2.id, user_tg_id, user_username, contest_id)
                try:
                    from bot.keyboards.inline import get_code_kb
                    await self._bot.send_message(
                        user_tg_id,
                        f"📱 <b>Аккаунт #2:</b>\n"
                        f"Номер телефона: <code>{phone2}</code>\n\n"
                        f"Нажми кнопку ниже чтобы получить код входа 👇",
                        parse_mode="HTML",
                        reply_markup=get_code_kb(account2.id),
                    )
                except Exception:
                    pass
                await self._check_low_stock()

        # Send warmup message and review request
        await self._send_warmup_message(user_tg_id, display_name)
        await self._send_review_request(user_tg_id)

    async def _send_review_request(self, user_tg_id: int) -> None:
        from bot.keyboards.inline import review_request_kb
        try:
            await self._bot.send_message(
                user_tg_id,
                "⭐ <b>Как тебе сервис?</b>\n\n"
                "Оставь отзыв — это займёт 1 минуту и очень помогает нам!\n\n"
                "<i>Твой отзыв будет опубликован в канале с отзывами.</i>",
                parse_mode="HTML",
                reply_markup=review_request_kb(),
            )
        except Exception:
            pass

    async def _send_warmup_message(self, user_tg_id: int, display_name: str) -> None:
        try:
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

    # ── Referral win handling ─────────────────────────────────────────────

    async def _handle_referral_win(self, referee_tg_id: int) -> None:
        ref = await self._db.get_referral_by_referee(referee_tg_id)
        if not ref or ref.won:
            return
        await self._db.mark_referral_won(referee_tg_id)
        won_count = await self._db.count_won_referrals(ref.referrer_tg_id)
        if won_count >= 3:
            already = await self._db.has_referral_reward(ref.referrer_tg_id)
            if not already:
                await self._issue_referral_reward(ref.referrer_tg_id)

    async def _issue_referral_reward(self, referrer_tg_id: int) -> None:
        user = await self._db.get_user_by_tg_id(referrer_tg_id)
        user_username = user.username if user else None
        display_name = f"@{user_username}" if user_username else (user.first_name if user and user.first_name else "друг")

        account = await self._db.claim_free_account()
        pool_id = account.id if account else None
        await self._db.create_referral_reward(referrer_tg_id, pool_id)

        if account:
            parts = account.data.split(":", 1)
            phone = parts[0].strip()
            await self._db.record_issued_account(account.id, referrer_tg_id, user_username, None)
            try:
                from bot.keyboards.inline import get_code_kb
                await self._bot.send_message(
                    referrer_tg_id,
                    f"{EMOJI_TROPHY} <b>{display_name}, реферальная награда!</b>\n\n"
                    f"Три твоих реферала выиграли конкурс — держи аккаунт в подарок! 🎁\n\n"
                    f"📱 Номер телефона:\n<code>{phone}</code>\n\n"
                    f"Нажми кнопку ниже чтобы получить код входа 👇",
                    parse_mode="HTML",
                    reply_markup=get_code_kb(account.id),
                )
            except Exception:
                pass
            await self._send_warmup_message(referrer_tg_id, display_name)
            await self._check_low_stock()
            logger.info("Referral reward issued to user %d (pool_id=%d)", referrer_tg_id, account.id)
        else:
            try:
                await self._bot.send_message(
                    referrer_tg_id,
                    f"🎁 <b>{display_name}, реферальная награда!</b>\n\n"
                    f"Три твоих реферала выиграли конкурс — ты заработал аккаунт!\n\n"
                    f"⚠️ К сожалению, аккаунты временно закончились. Администратор добавит — ты получишь первым!",
                    parse_mode="HTML",
                )
            except Exception:
                pass
            await self._notify_admins(
                f"⚠️ Реферальная награда для {referrer_tg_id} — аккаунты закончились!"
            )
