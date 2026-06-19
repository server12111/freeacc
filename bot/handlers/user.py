import logging
from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup

from bot.config import Config
from bot.database.db import Database
from bot.keyboards.inline import (
    get_code_kb, confirm_create_contest_kb,
    check_payment_kb, tutorial_kb, subscription_wall_kb,
    referral_kb, back_to_menu_kb, cancel_review_kb, progress_kb,
    ads_main_kb, ads_section_kb, ads_item_kb,
)
from bot.constants import (
    EMOJI_WELCOME, EMOJI_CONFETTI, EMOJI_TROPHY,
    EMOJI_BOOK, EMOJI_ERROR, EMOJI_PROGRESS,
    E_LINK, E_UNLOCK, E_LOADING, E_SETTINGS,
    E_WALLET, E_COIN, E_CHECK, E_CROSS, E_LOCK,
    E_GIFT, E_INFO, E_BELL, E_CLOCK,
)

router = Router()
logger = logging.getLogger(__name__)


class UserStates(StatesGroup):
    waiting_review = State()


async def _menu_kb(db: Database, has_contest: bool = False) -> InlineKeyboardMarkup:
    from bot.keyboards.inline import main_menu_kb
    reviews_url = await db.get_setting("reviews_url", "")
    return main_menu_kb(has_contest=has_contest, reviews_url=reviews_url)


def _build_progress_text(count: int, offset: int = 0, link: str = "") -> str:
    unlocked = []
    if count >= 10:
        unlocked.append("1 аккаунт")
    if count >= 20:
        unlocked.append("2 дня рассылки @feAutoSenderbot")
    if count >= 30:
        unlocked.append("ещё +1 аккаунт")

    lines = [f"{EMOJI_PROGRESS} <b>Твой прогресс</b>"]

    if unlocked:
        lines.append("")
        lines.append(f"✅ {unlocked[0]} — уже твой при завершении!")
        for item in unlocked[1:]:
            suffix = "твои" if "рассылки" in item else "твой"
            lines.append(f"✅ {item} — тоже {suffix}!")

    if count < 10:
        tier_start, tier_end, next_label = 0, 10, "1 аккаунт"
    elif count < 20:
        tier_start, tier_end, next_label = 10, 20, "2 дня рассылки @feAutoSenderbot"
    elif count < 30:
        tier_start, tier_end, next_label = 20, 30, "ещё +1 аккаунт"
    else:
        tier_start = tier_end = next_label = None

    lines.append("")
    if tier_end is not None:
        within = count - tier_start
        bars = "🟩" * within + "⬜" * (tier_end - tier_start - within)
        left = tier_end - count
        lines.append(f"{bars}  <b>{count} чел.</b>")
        lines.append(f"➡️ Ещё <b>{left} чел.</b> — {next_label}")
    else:
        lines.append("🏆 <b>Максимальный тир!</b> Ждём итогов конкурса.")

    if link:
        lines.append(f"\n{E_LINK} <b>Твоя ссылка:</b>\n<a href=\"{link}\">{link}</a>")

    return "\n".join(lines)


async def _handle_referral_param(message: Message, db: Database, ref_param: str) -> None:
    if not ref_param.isdigit():
        return
    referrer_id = int(ref_param)
    if referrer_id == message.from_user.id:
        return
    existing = await db.get_referral_by_referee(message.from_user.id)
    if existing:
        return
    is_winner = await db.is_account_recipient(message.from_user.id)
    if is_winner:
        return
    await db.create_referral(referrer_id, message.from_user.id)
    logger.info("Referral created: referrer=%d referee=%d", referrer_id, message.from_user.id)


@router.message(CommandStart())
async def cmd_start(message: Message, db: Database, config: Config) -> None:
    args = (message.text or "").split(maxsplit=1)
    if len(args) > 1 and args[1].startswith("ref_"):
        await _handle_referral_param(message, db, args[1][4:])

    contest = await db.get_user_current_contest(message.from_user.id)
    name = message.from_user.first_name or "друг"
    await message.answer(
        f"{EMOJI_WELCOME} <b>Бесплатные аккаунты</b>\n\n"
        f"Привет, <b>{name}</b>! 👋\n\n"
        f"Хочешь получить Telegram-аккаунт <b>бесплатно</b>?\n\n"
        f"<b>Награды за участников конкурса:</b>\n"
        f"• 10 чел. → 1 аккаунт\n"
        f"• 20 чел. → 2 дня рассылки @feAutoSenderbot\n"
        f"• 30 чел. → ещё +1 аккаунт\n\n"
        f"Или купи аккаунт сразу за <b>$0.5</b> {E_WALLET}\n\n"
        f"Выбирай 👇",
        parse_mode="HTML",
        reply_markup=await _menu_kb(db, has_contest=bool(contest)),
    )


@router.callback_query(F.data == "back_to_menu")
async def cb_back_to_menu(callback: CallbackQuery, db: Database) -> None:
    await callback.answer()
    contest = await db.get_user_current_contest(callback.from_user.id)
    await callback.message.edit_text(
        "Главное меню 👇",
        reply_markup=await _menu_kb(db, has_contest=bool(contest)),
    )


@router.callback_query(F.data == "tutorial")
async def cb_tutorial(callback: CallbackQuery, db: Database, config: Config) -> None:
    await callback.answer()
    text = await db.get_setting("tutorial_text", "")
    video_id = await db.get_setting("tutorial_video_id", "")

    if not text:
        text = (
            f"{EMOJI_BOOK} <b>Как получить аккаунт бесплатно:</b>\n\n"
            f"<b>1.</b> Нажми «Получить бесплатно»\n"
            f"<b>2.</b> Бот создаёт личный конкурс в канале\n"
            f"<b>3.</b> Ты получишь уникальную реферальную ссылку\n"
            f"<b>4.</b> Поделись ею с друзьями\n\n"
            f"<b>Награды:</b>\n"
            f"• 10 чел. → 1 аккаунт {E_UNLOCK}\n"
            f"• 20 чел. → 2 дня рассылки @feAutoSenderbot\n"
            f"• 30 чел. → ещё +1 аккаунт\n\n"
            f"{E_WALLET} Не хочешь ждать? Купи аккаунт сразу за <b>$0.5</b>."
        )

    if video_id:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer_video(
            video=video_id,
            caption=text,
            parse_mode="HTML",
            reply_markup=tutorial_kb(),
        )
    else:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=tutorial_kb())


@router.callback_query(F.data == "check_subscription")
async def cb_check_subscription(callback: CallbackQuery, config: Config, db: Database) -> None:
    await callback.answer()
    from bot.middlewares.subscription import SubscriptionMiddleware
    SubscriptionMiddleware._cache.pop(callback.from_user.id, None)

    try:
        member = await callback.bot.get_chat_member(int(config.CHANNEL_ID), callback.from_user.id)
        is_sub = member.status in {"member", "administrator", "creator", "restricted"}
    except Exception:
        is_sub = False

    if is_sub:
        contest = await db.get_user_current_contest(callback.from_user.id)
        await callback.message.edit_text(
            f"{E_CHECK} Подписка подтверждена! Добро пожаловать 👋",
            parse_mode="HTML",
            reply_markup=await _menu_kb(db, has_contest=bool(contest)),
        )
    else:
        await callback.message.edit_text(
            f"{E_CROSS} Ты ещё не подписался.\n\nПодпишись на канал и нажми кнопку снова.",
            parse_mode="HTML",
            reply_markup=subscription_wall_kb(config.CHANNEL_ID),
        )


@router.callback_query(F.data == "get_account")
async def cb_get_account(callback: CallbackQuery, db: Database, config: Config) -> None:
    user = callback.from_user
    await callback.answer()

    existing = await db.get_user_current_contest(user.id)
    if existing:
        if existing.status == "pending":
            start_time = await db.get_setting("contest_start_time", "")
            launch_info = f"сегодня в {start_time}" if start_time else "в ближайшее время"
            await callback.message.edit_text(
                f"{E_CLOCK} <b>Заявка уже в очереди</b>\n\n"
                f"Конкурс запустится {launch_info}.\n"
                f"Ожидай уведомление!",
                parse_mode="HTML",
                reply_markup=back_to_menu_kb(),
            )
        elif existing.status == "active" and existing.piarflow_link:
            await _show_progress(callback.message, existing, db)
        else:
            await callback.message.edit_text(
                f"{E_LOADING} Твой конкурс уже создаётся...\nПодожди ~30 секунд.",
                parse_mode="HTML",
                reply_markup=back_to_menu_kb(),
            )
        return

    await callback.message.edit_text(
        f"{EMOJI_WELCOME} <b>Вот как это работает — займёт 2 минуты</b>\n\n"
        f"<b>1.</b> Нажимаешь кнопку ниже\n"
        f"<b>2.</b> Бот создаёт <i>личный</i> конкурс в канале\n"
        f"<b>3.</b> Получаешь уникальную ссылку\n"
        f"<b>4.</b> Делишься ею с друзьями {E_LINK}\n\n"
        f"{E_CHECK} Бесплатно — участники считаются заново каждый день\n\n"
        f"Готов? Жми 👇",
        parse_mode="HTML",
        reply_markup=confirm_create_contest_kb(),
    )


@router.callback_query(F.data == "confirm_create_contest")
async def cb_confirm_create_contest(
    callback: CallbackQuery, db: Database, config: Config, manager
) -> None:
    user = callback.from_user
    await callback.answer()

    existing = await db.get_user_current_contest(user.id)
    if existing:
        if existing.status == "pending":
            start_time = await db.get_setting("contest_start_time", "")
            launch_info = f"сегодня в {start_time}" if start_time else "в ближайшее время"
            await callback.message.edit_text(
                f"{E_CLOCK} Заявка уже в очереди. Запуск {launch_info}.",
                parse_mode="HTML",
                reply_markup=back_to_menu_kb(),
            )
        elif existing.piarflow_link:
            await _show_progress(callback.message, existing, db)
        else:
            await callback.message.edit_text(
                f"{E_LOADING} Конкурс уже создаётся...",
                parse_mode="HTML",
                reply_markup=back_to_menu_kb(),
            )
        return

    participant_number = await db.get_next_participant_number()

    await db.create_contest(
        owner_tg_id=user.id,
        channel_id=config.CHANNEL_ID,
        threshold=10,
        participant_number=participant_number,
        status="pending",
    )

    start_time = await db.get_setting("contest_start_time", "")
    launch_info = f"сегодня в <b>{start_time}</b>" if start_time else "<b>в ближайшее время</b>"

    await callback.message.edit_text(
        f"{E_CHECK} <b>Заявка принята!</b>\n\n"
        f"Твой конкурс будет запущен {launch_info}.\n"
        f"Как только стартует — пришлём уведомление со ссылкой.",
        parse_mode="HTML",
        reply_markup=back_to_menu_kb(),
    )


@router.callback_query(F.data == "my_progress")
async def cb_my_progress(callback: CallbackQuery, db: Database, config: Config) -> None:
    contest = await db.get_user_current_contest(callback.from_user.id)
    if not contest:
        await callback.answer("У тебя нет активного конкурса.", show_alert=True)
        return
    if contest.status == "pending":
        start_time = await db.get_setting("contest_start_time", "")
        launch_info = f"в {start_time}" if start_time else "скоро"
        await callback.message.edit_text(
            f"{E_CLOCK} <b>Заявка в очереди</b>\n\n"
            f"Конкурс запустится {launch_info}.\n"
            f"Ожидай уведомление!",
            parse_mode="HTML",
            reply_markup=back_to_menu_kb(),
        )
    else:
        await _show_progress(callback.message, contest, db)
    await callback.answer()


@router.callback_query(F.data == "referrals")
async def cb_referrals(callback: CallbackQuery, db: Database) -> None:
    await callback.answer()
    user_id = callback.from_user.id
    me = await callback.bot.get_me()
    bot_username = me.username or ""

    won_count = await db.count_won_referrals(user_id)
    all_count = await db.count_all_referrals(user_id)
    has_reward = await db.has_referral_reward(user_id)

    link = f"https://t.me/{bot_username}?start=ref_{user_id}"

    bars_won = "🟩" * won_count + "⬜" * max(0, 3 - won_count)
    progress_line = f"{bars_won}  <b>{won_count} / 3</b> победивших"

    if has_reward:
        status_line = f"{E_CHECK} <b>Реферальная награда уже получена!</b>"
    elif won_count >= 3:
        status_line = f"{E_CHECK} <b>Условие выполнено!</b> Аккаунт скоро придёт."
    else:
        left = 3 - won_count
        status_line = f"Ещё <b>{left} победивших реферала</b> — и аккаунт твой {E_UNLOCK}"

    text = (
        f"👥 <b>Реферальная программа</b>\n\n"
        f"Пригласи 3 человек, которые <b>выиграют конкурс</b> — получи аккаунт бесплатно!\n\n"
        f"📊 Прогресс:\n{progress_line}\n{status_line}\n\n"
        f"📋 Всего приглашено: <b>{all_count}</b>\n\n"
        f"🔗 <b>Твоя ссылка:</b>\n<code>{link}</code>\n\n"
        f"⚠️ <i>Победители предыдущих конкурсов не засчитываются как рефералы.</i>"
    )
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=referral_kb(bot_username, user_id),
    )


@router.callback_query(F.data.startswith("copy_ref:"))
async def cb_copy_ref(callback: CallbackQuery) -> None:
    parts = callback.data.split(":", 2)
    user_id = parts[1]
    bot_username = parts[2] if len(parts) > 2 else ""
    link = f"https://t.me/{bot_username}?start=ref_{user_id}"
    await callback.answer(text=link, show_alert=True)


@router.callback_query(F.data == "buy_account")
async def cb_buy_account(callback: CallbackQuery, db: Database, config: Config) -> None:
    await callback.answer()

    from bot.services.cryptobot import CryptoBotService
    crypto = CryptoBotService(config.CRYPTO_BOT_TOKEN)
    if not crypto.is_configured():
        await callback.message.edit_text(
            f"{EMOJI_ERROR} Оплата временно недоступна.\nОбратитесь к администратору.",
            parse_mode="HTML",
            reply_markup=back_to_menu_kb(),
        )
        return

    await db.cancel_pending_purchases(callback.from_user.id)

    amount = config.ACCOUNT_PRICE_USDT
    invoice = await crypto.create_invoice(
        amount=amount,
        description=f"Telegram аккаунт — {amount} USDT",
        payload=str(callback.from_user.id),
    )
    if not invoice:
        await callback.message.edit_text(
            f"{EMOJI_ERROR} Не удалось создать счёт. Попробуй позже.",
            parse_mode="HTML",
            reply_markup=back_to_menu_kb(),
        )
        return

    invoice_id = str(invoice["invoice_id"])
    pay_url = invoice["pay_url"]
    await db.create_purchase(callback.from_user.id, invoice_id, amount)

    await callback.message.edit_text(
        f"{E_WALLET} <b>Покупка аккаунта</b>\n\n"
        f"Сумма: <b>{amount} USDT</b>\n\n"
        f"<b>Как оплатить:</b>\n"
        f"<b>1.</b> Нажми «Я оплатил» — откроется @CryptoBot\n"
        f"<b>2.</b> Выполни оплату\n"
        f"<b>3.</b> Вернись сюда и нажми «Я оплатил»\n\n"
        f'<a href="{pay_url}">{E_COIN} Оплатить {amount} USDT</a>',
        parse_mode="HTML",
        reply_markup=check_payment_kb(invoice_id),
        disable_web_page_preview=True,
    )


@router.callback_query(F.data.startswith("check_payment:"))
async def cb_check_payment(
    callback: CallbackQuery, db: Database, config: Config, manager
) -> None:
    invoice_id = callback.data.split(":", 1)[1]
    await callback.answer()

    from bot.services.cryptobot import CryptoBotService
    crypto = CryptoBotService(config.CRYPTO_BOT_TOKEN)

    purchase = await db.get_purchase_by_invoice(invoice_id)
    if not purchase or purchase.user_tg_id != callback.from_user.id:
        await callback.message.edit_text(
            f"{EMOJI_ERROR} Счёт не найден.",
            parse_mode="HTML",
            reply_markup=back_to_menu_kb(),
        )
        return

    if purchase.status == "paid":
        await callback.message.edit_text(
            f"{E_CHECK} Аккаунт уже был выдан по этому счёту.",
            parse_mode="HTML",
            reply_markup=back_to_menu_kb(),
        )
        return

    invoice = await crypto.get_invoice(invoice_id)
    if not invoice:
        await callback.message.edit_text(
            f"{EMOJI_ERROR} Не удалось проверить оплату. Попробуй ещё раз.",
            parse_mode="HTML",
            reply_markup=check_payment_kb(invoice_id),
        )
        return

    if invoice.get("status") != "paid":
        await callback.message.edit_text(
            f"{E_LOADING} Оплата ещё не поступила.\n\n"
            "Убедись что завершил оплату в @CryptoBot, затем нажми снова.",
            parse_mode="HTML",
            reply_markup=check_payment_kb(invoice_id),
        )
        return

    from bot.services.account_issuer import AccountIssuerService
    issuer = AccountIssuerService(callback.bot, db, config)
    issued = await issuer.issue(
        user_tg_id=callback.from_user.id,
        user_username=callback.from_user.username,
        contest_id=None,
    )

    if not issued:
        await callback.message.edit_text(
            f"⚠️ Оплата получена, но аккаунты временно закончились.\n"
            "Администратор добавит — ты получишь первым!",
            reply_markup=back_to_menu_kb(),
        )
        await db.add_log("buy_no_stock", f"user={callback.from_user.id} invoice={invoice_id}")
        return

    # Mark purchase paid using last issued pool_id
    history = await db.get_issued_history(1)
    if history and history[0].user_tg_id == callback.from_user.id:
        await db.mark_purchase_paid(invoice_id, history[0].pool_id)

    await callback.message.edit_text(
        f"{E_CHECK} Оплата прошла — аккаунт выдан! Смотри сообщение выше.",
        parse_mode="HTML",
        reply_markup=back_to_menu_kb(),
    )
    await db.add_log("account_bought", f"user={callback.from_user.id} invoice={invoice_id}")


@router.callback_query(F.data == "cancel_payment")
async def cb_cancel_payment(callback: CallbackQuery, db: Database) -> None:
    await callback.answer()
    await db.cancel_pending_purchases(callback.from_user.id)
    await callback.message.edit_text("Покупка отменена.", reply_markup=back_to_menu_kb())


@router.callback_query(F.data.startswith("get_code:"))
async def cb_get_code(callback: CallbackQuery, db: Database, manager) -> None:
    pool_id = int(callback.data.split(":")[1])
    await callback.answer()

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    account = await db.get_account_by_id(pool_id)
    if not account:
        await callback.message.answer(f"{EMOJI_ERROR} Аккаунт не найден.", parse_mode="HTML")
        return

    parts = account.data.split(":", 1)
    phone = parts[0].strip()
    session_str = parts[1].strip() if len(parts) > 1 else ""

    if not session_str:
        await callback.message.answer(
            f"{EMOJI_ERROR} Нет данных для этого аккаунта. Обратитесь к администратору.",
            parse_mode="HTML",
        )
        return

    if not manager.is_connected:
        await callback.message.answer(
            f"{EMOJI_ERROR} Система недоступна. Обратитесь к администратору.",
            parse_mode="HTML",
        )
        return

    status_msg = await callback.message.answer(
        f"{E_LOADING} Ищем последний код входа...",
        parse_mode="HTML",
    )
    code = await manager.get_telegram_auth_code(phone, session_str)

    if code:
        await status_msg.edit_text(
            f"🔑 Код входа: <code>{code}</code>\n\n"
            "Код действует ~2 минуты.\n"
            "Не подошёл? Войди в Telegram заново — придёт новый код, затем запроси его здесь:",
            parse_mode="HTML",
            reply_markup=get_code_kb(pool_id, retry=True),
        )
    else:
        await status_msg.edit_text(
            f"{EMOJI_ERROR} Код не найден в истории.\n\n"
            "Попробуй войти в Telegram с этим номером — придёт код, затем нажми кнопку:",
            parse_mode="HTML",
            reply_markup=get_code_kb(pool_id),
        )


async def _show_progress(message, contest, db: Database) -> None:
    text = _build_progress_text(contest.invite_count, contest.invite_count_offset, contest.piarflow_link or "")
    kb = progress_kb(contest.piarflow_link or "")
    await message.edit_text(text, parse_mode="HTML", reply_markup=kb)


async def _show_progress_msg(message: Message, contest, db: Database, send: bool = False) -> None:
    text = _build_progress_text(contest.invite_count, contest.invite_count_offset, contest.piarflow_link or "")
    kb = progress_kb(contest.piarflow_link or "")
    if send:
        await message.answer(text, parse_mode="HTML", reply_markup=kb)
    else:
        await message.edit_text(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data == "ads")
async def cb_ads(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.edit_text(
        "📢 <b>Реклама</b>\n\n"
        "Здесь ты найдёшь наши проекты и партнёров.\n"
        "Выбери раздел 👇",
        parse_mode="HTML",
        reply_markup=ads_main_kb(),
    )


@router.callback_query(F.data.startswith("ads_section:"))
async def cb_ads_section(callback: CallbackQuery, db: Database) -> None:
    await callback.answer()
    section = callback.data.split(":")[1]
    items = await db.get_ads_items(section)
    label = "📁 Наши проекты" if section == "project" else "💼 Спонсоры"
    if items:
        text = f"<b>{label}</b>\n\nВыбери:"
    else:
        text = f"<b>{label}</b>\n\nПока пусто."
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=ads_section_kb(items, section))


@router.callback_query(F.data.startswith("ads_item:"))
async def cb_ads_item(callback: CallbackQuery, db: Database) -> None:
    await callback.answer()
    item_id = int(callback.data.split(":")[1])
    item = await db.get_ads_item(item_id)
    if not item:
        await callback.message.edit_text("Элемент не найден.", reply_markup=ads_main_kb())
        return
    await callback.message.edit_text(item.text, parse_mode="HTML", reply_markup=ads_item_kb(item.type))


@router.callback_query(F.data == "write_review")
async def cb_write_review(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(UserStates.waiting_review)
    await callback.message.edit_text(
        "✍️ <b>Напиши свой отзыв</b>\n\n"
        "Просто отправь текст — мы опубликуем его в нашем канале 🙏\n\n"
        "<i>Расскажи как получил аккаунт, доволен ли результатом!</i>",
        parse_mode="HTML",
        reply_markup=cancel_review_kb(),
    )


@router.callback_query(F.data == "skip_review")
async def cb_skip_review(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    await callback.answer()
    await state.clear()
    await callback.message.edit_text("Главное меню 👇", reply_markup=await _menu_kb(db))


@router.message(UserStates.waiting_review)
async def handle_review_text(message: Message, db: Database, state: FSMContext) -> None:
    channel_id = await db.get_setting("reviews_channel_id", "")
    if channel_id:
        try:
            await message.bot.copy_message(
                chat_id=int(channel_id),
                from_chat_id=message.chat.id,
                message_id=message.message_id,
            )
        except Exception:
            pass
    await state.clear()
    await message.answer(
        "🙏 <b>Спасибо за отзыв!</b>\n\nМы ценим твоё мнение!",
        parse_mode="HTML",
        reply_markup=await _menu_kb(db),
    )
