import logging
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError

from bot.config import Config
from bot.database.db import Database
from bot.keyboards.inline import (
    admin_menu_kb, accounts_menu_kb, contests_menu_kb, back_to_admin_kb,
    contest_actions_kb, settings_menu_kb, cancel_kb, confirm_finish_kb,
    tutorial_admin_kb, subscription_admin_kb, broadcast_confirm_kb,
    schedule_kb, promos_admin_kb, admin_ads_kb,
)
from bot.constants import (
    E_SETTINGS, E_BOX, E_CHART, E_BROADCAST, E_FILE,
    E_CHECK, E_CROSS, E_BELL, E_INFO, E_PENCIL, E_MEDIA, E_TRASH,
    E_LOADING, E_CHART_UP,
)

logger = logging.getLogger(__name__)
router = Router()

# Temporary storage for in-progress account login flows
_pending_account_auth: dict = {}  # admin_tg_id -> {'client': TelegramClient, 'phone': str}


def _is_admin(config: Config, tg_id: int) -> bool:
    return tg_id in config.ADMIN_IDS


async def _cleanup_pending(admin_id: int) -> None:
    entry = _pending_account_auth.pop(admin_id, None)
    if entry:
        try:
            await entry["client"].disconnect()
        except Exception:
            pass


# ── States ─────────────────────────────────────────────────────────────────

class AdminStates(StatesGroup):
    waiting_threshold = State()
    waiting_parse_pattern = State()
    waiting_notify_text = State()
    waiting_piarflow_steps = State()
    waiting_tutorial_text = State()
    waiting_tutorial_video = State()
    waiting_broadcast_msg = State()
    waiting_reviews_url = State()
    waiting_reviews_channel_id = State()
    waiting_start_time = State()
    waiting_end_time = State()
    waiting_promo_codes = State()
    waiting_ads_name = State()
    waiting_ads_text = State()
    # Account add flow
    add_account_phone = State()
    add_account_code = State()
    add_account_2fa = State()
    # Userbot auth flow
    auth_phone = State()
    auth_code = State()
    auth_password = State()


# ── Entry ──────────────────────────────────────────────────────────────────

@router.message(Command("admin"))
async def cmd_admin(message: Message, config: Config, db: Database, state: FSMContext) -> None:
    await state.clear()
    if not _is_admin(config, message.from_user.id):
        await message.answer("⛔ Нет доступа.")
        return
    free = await db.get_free_accounts_count()
    active = await db.get_active_contests()
    await message.answer(
        f"{E_SETTINGS} <b>Панель администратора</b>\n\n"
        f"{E_BOX} Свободных аккаунтов: <b>{free}</b>\n"
        f"{E_CHART_UP} Активных конкурсов: <b>{len(active)}</b>",
        parse_mode="HTML",
        reply_markup=admin_menu_kb(),
    )


@router.callback_query(F.data == "admin_menu")
async def cb_admin_menu(callback: CallbackQuery, config: Config, db: Database, state: FSMContext) -> None:
    await _cleanup_pending(callback.from_user.id)
    await state.clear()
    if not _is_admin(config, callback.from_user.id):
        await callback.answer("⛔ Нет доступа.", show_alert=True)
        return
    free = await db.get_free_accounts_count()
    active = await db.get_active_contests()
    await callback.message.edit_text(
        f"{E_SETTINGS} <b>Панель администратора</b>\n\n"
        f"{E_BOX} Свободных аккаунтов: <b>{free}</b>\n"
        f"{E_CHART_UP} Активных конкурсов: <b>{len(active)}</b>",
        parse_mode="HTML",
        reply_markup=admin_menu_kb(),
    )
    await callback.answer()


# ── Accounts ───────────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin_accounts")
async def cb_accounts(callback: CallbackQuery, config: Config) -> None:
    if not _is_admin(config, callback.from_user.id):
        await callback.answer()
        return
    await callback.message.edit_text("💼 Управление аккаунтами", reply_markup=accounts_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "accounts_stats")
async def cb_accounts_stats(callback: CallbackQuery, config: Config, db: Database) -> None:
    if not _is_admin(config, callback.from_user.id):
        await callback.answer()
        return
    free = await db.get_free_accounts_count()
    issued = await db.get_issued_accounts_count()
    await callback.message.edit_text(
        f"📊 Пул аккаунтов\n\n✅ Свободных: {free}\n📤 Выдано: {issued}\n📦 Всего: {free + issued}",
        reply_markup=accounts_menu_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "accounts_history")
async def cb_accounts_history(callback: CallbackQuery, config: Config, db: Database) -> None:
    if not _is_admin(config, callback.from_user.id):
        await callback.answer()
        return
    history = await db.get_issued_history(20)
    if not history:
        text = "📜 История выдач пуста."
    else:
        lines = []
        for h in history:
            uname = f"@{h.user_username}" if h.user_username else str(h.user_tg_id)
            lines.append(f"• {h.issued_at[:16]} — {uname}")
        text = "📜 Последние выдачи:\n\n" + "\n".join(lines)
    await callback.message.edit_text(text, reply_markup=accounts_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "add_accounts")
async def cb_add_accounts(callback: CallbackQuery, config: Config, state: FSMContext) -> None:
    if not _is_admin(config, callback.from_user.id):
        await callback.answer()
        return
    await _cleanup_pending(callback.from_user.id)
    await state.set_state(AdminStates.add_account_phone)
    await callback.message.edit_text(
        "➕ Добавление аккаунта\n\n"
        "Введи номер телефона аккаунта:\n"
        "<code>+79001234567</code>",
        parse_mode="HTML",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(AdminStates.add_account_phone)
async def handle_add_account_phone(
    message: Message, config: Config, state: FSMContext
) -> None:
    if not _is_admin(config, message.from_user.id):
        return
    phone = message.text.strip()
    client = TelegramClient(
        StringSession(),
        config.USERBOT_API_ID,
        config.USERBOT_API_HASH,
    )
    try:
        await client.connect()
        await client.send_code_request(phone)
        _pending_account_auth[message.from_user.id] = {"client": client, "phone": phone}
        await state.set_state(AdminStates.add_account_code)
        await message.answer(
            f"📨 Код отправлен на <code>{phone}</code>.\n\nВведи код из SMS:",
            parse_mode="HTML",
            reply_markup=cancel_kb(),
        )
    except Exception as exc:
        await client.disconnect()
        await state.clear()
        await message.answer(f"❌ Ошибка: {exc}", reply_markup=cancel_kb())


@router.message(AdminStates.add_account_code)
async def handle_add_account_code(
    message: Message, config: Config, db: Database, state: FSMContext
) -> None:
    if not _is_admin(config, message.from_user.id):
        return
    entry = _pending_account_auth.get(message.from_user.id)
    if not entry:
        await message.answer("⚠️ Сессия истекла. Начни заново.", reply_markup=accounts_menu_kb())
        await state.clear()
        return
    try:
        await entry["client"].sign_in(entry["phone"], message.text.strip())
        session_str = entry["client"].session.save()
        phone = entry["phone"]
        await _cleanup_pending(message.from_user.id)
        await db.add_accounts([f"{phone}:{session_str}"], message.from_user.id)
        await db.add_log("account_added", f"phone={phone}", message.from_user.id)
        await state.clear()
        await message.answer(
            f"✅ Аккаунт <code>{phone}</code> добавлен в пул!",
            parse_mode="HTML",
            reply_markup=accounts_menu_kb(),
        )
    except SessionPasswordNeededError:
        await state.set_state(AdminStates.add_account_2fa)
        await message.answer("🔐 Введи пароль двухфакторной аутентификации:", reply_markup=cancel_kb())
    except PhoneCodeInvalidError:
        await message.answer("❌ Неверный код. Попробуй ещё раз:", reply_markup=cancel_kb())
    except Exception as exc:
        await _cleanup_pending(message.from_user.id)
        await state.clear()
        await message.answer(f"❌ Ошибка: {exc}", reply_markup=accounts_menu_kb())


@router.message(AdminStates.add_account_2fa)
async def handle_add_account_2fa(
    message: Message, config: Config, db: Database, state: FSMContext
) -> None:
    if not _is_admin(config, message.from_user.id):
        return
    entry = _pending_account_auth.get(message.from_user.id)
    if not entry:
        await message.answer("⚠️ Сессия истекла. Начни заново.", reply_markup=accounts_menu_kb())
        await state.clear()
        return
    try:
        await entry["client"].sign_in(password=message.text.strip())
        session_str = entry["client"].session.save()
        phone = entry["phone"]
        await _cleanup_pending(message.from_user.id)
        await db.add_accounts([f"{phone}:{session_str}"], message.from_user.id)
        await db.add_log("account_added", f"phone={phone}", message.from_user.id)
        await state.clear()
        await message.answer(
            f"✅ Аккаунт <code>{phone}</code> добавлен в пул!",
            parse_mode="HTML",
            reply_markup=accounts_menu_kb(),
        )
    except Exception as exc:
        await _cleanup_pending(message.from_user.id)
        await state.clear()
        await message.answer(f"❌ Ошибка: {exc}", reply_markup=accounts_menu_kb())


# ── Contests ───────────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin_contests")
async def cb_contests(callback: CallbackQuery, config: Config) -> None:
    if not _is_admin(config, callback.from_user.id):
        await callback.answer()
        return
    await callback.message.edit_text("🏆 Конкурсы", reply_markup=contests_menu_kb())
    await callback.answer()


async def _owner_label(db: Database, tg_id: int) -> str:
    user = await db.get_user_by_tg_id(tg_id)
    if user and user.username:
        return f"@{user.username}"
    if user and user.first_name:
        return user.first_name
    return str(tg_id)


@router.callback_query(F.data == "list_contests")
async def cb_list_contests(callback: CallbackQuery, config: Config, db: Database) -> None:
    await callback.answer()
    if not _is_admin(config, callback.from_user.id):
        await callback.answer()
        return
    try:
        contests = await db.get_all_contests()
    except Exception as exc:
        logger.exception("list_contests db error: %s", exc)
        await callback.message.edit_text("❌ Ошибка загрузки.", reply_markup=contests_menu_kb())
        return
    if not contests:
        await callback.message.edit_text("Конкурсов пока нет.", reply_markup=contests_menu_kb())
        return
    status_icons = {"pending": "🕐", "active": "🟢", "finished": "🏁", "expired": "⏱", "failed": "❌"}
    lines = []
    for c in contests[:20]:
        icon = status_icons.get(c.status, "❓")
        link_info = "✔" if c.piarflow_link else "⏳"
        owner = await _owner_label(db, c.owner_tg_id)
        effective = max(0, c.invite_count - c.invite_count_offset)
        lines.append(
            f"{icon} #{c.id} | {owner} | {effective}/{c.invite_threshold} | {link_info}"
        )
    text = "📋 <b>Конкурсы (последние 20):</b>\n\n" + "\n".join(lines)
    text += "\n\n/contest &lt;ID&gt; — детали"
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=contests_menu_kb())
    except Exception:
        pass


@router.message(Command("contest"))
async def cmd_contest_detail(message: Message, config: Config, db: Database) -> None:
    if not _is_admin(config, message.from_user.id):
        return
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("Использование: /contest <ID>")
        return
    contest = await db.get_contest(int(args[1]))
    if not contest:
        await message.answer("Конкурс не найден.")
        return
    text = (
        f"🏆 Конкурс #{contest.id}\n\n"
        f"Владелец: {contest.owner_tg_id}\n"
        f"Канал: {contest.channel_id}\n"
        f"Статус: {contest.status}\n"
        f"Порог: {contest.invite_threshold}\n"
        f"Приглашено: {contest.invite_count}\n"
        f"Ссылка: {contest.piarflow_link or 'нет'}\n"
        f"Создан: {contest.created_at[:16]}"
    )
    await message.answer(text, reply_markup=contest_actions_kb(contest.id, contest.status))


@router.callback_query(F.data.startswith("contest_detail:"))
async def cb_contest_detail(callback: CallbackQuery, config: Config, db: Database) -> None:
    if not _is_admin(config, callback.from_user.id):
        await callback.answer()
        return
    contest_id = int(callback.data.split(":")[1])
    contest = await db.get_contest(contest_id)
    if not contest:
        await callback.answer("Не найден.", show_alert=True)
        return
    text = (
        f"🏆 Конкурс #{contest.id}\n\n"
        f"Владелец: {contest.owner_tg_id}\n"
        f"Статус: {contest.status}\n"
        f"Приглашено: {contest.invite_count}/{contest.invite_threshold}\n"
        f"Ссылка: {contest.piarflow_link or 'нет'}"
    )
    await callback.message.edit_text(text, reply_markup=contest_actions_kb(contest.id, contest.status))
    await callback.answer()


@router.callback_query(F.data.startswith("contest_finish:"))
async def cb_contest_finish(callback: CallbackQuery, config: Config) -> None:
    if not _is_admin(config, callback.from_user.id):
        await callback.answer()
        return
    contest_id = int(callback.data.split(":")[1])
    await callback.message.edit_text(
        f"Завершить конкурс #{contest_id}?",
        reply_markup=confirm_finish_kb(contest_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("contest_finish_confirm:"))
async def cb_contest_finish_confirm(callback: CallbackQuery, config: Config, db: Database) -> None:
    if not _is_admin(config, callback.from_user.id):
        await callback.answer()
        return
    contest_id = int(callback.data.split(":")[1])
    await db.set_contest_status(contest_id, "finished")
    await db.add_log("contest_finished", f"contest={contest_id}", callback.from_user.id)
    await callback.message.edit_text(f"🏁 Конкурс #{contest_id} завершён.", reply_markup=back_to_admin_kb())
    await callback.answer()


# ── Settings ───────────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin_settings")
async def cb_settings(callback: CallbackQuery, config: Config, db: Database) -> None:
    if not _is_admin(config, callback.from_user.id):
        await callback.answer()
        return
    pattern = await db.get_setting("parse_pattern", "")
    start_t = await db.get_setting("contest_start_time", "—")
    end_t = await db.get_setting("contest_end_time", "—")
    text = (
        f"⚙️ <b>Настройки</b>\n\n"
        f"🏆 Тиры: 10 / 20 / 30 участников (фиксированы)\n"
        f"🕐 Расписание: {start_t or '—'} → {end_t or '—'} (Киев)\n"
        f"🔍 Regex: {pattern or '(дефолтный)'}"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=settings_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "set_parse_pattern")
async def cb_set_parse_pattern(callback: CallbackQuery, config: Config, state: FSMContext) -> None:
    if not _is_admin(config, callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(AdminStates.waiting_parse_pattern)
    await callback.message.edit_text(
        "Введи regex для извлечения числа приглашений из текста @PiarFlowBot.\n"
        "Нужна 1 группа захвата: (<b>число</b>).\n\n"
        "Пример: <code>(\\d+)\\s*из\\s*\\d+</code>\n\n"
        "Отправь <code>-</code> для сброса на дефолтный.",
        parse_mode="HTML",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(AdminStates.waiting_parse_pattern)
async def handle_parse_pattern(message: Message, config: Config, db: Database, state: FSMContext) -> None:
    if not _is_admin(config, message.from_user.id):
        return
    val = "" if message.text.strip() == "-" else message.text.strip()
    await db.set_setting("parse_pattern", val)
    await state.clear()
    await message.answer(f"✅ Паттерн: <code>{val or '(дефолтный)'}</code>",
                         parse_mode="HTML", reply_markup=settings_menu_kb())


@router.callback_query(F.data == "set_notify_text")
async def cb_set_notify_text(callback: CallbackQuery, config: Config, state: FSMContext) -> None:
    if not _is_admin(config, callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(AdminStates.waiting_notify_text)
    await callback.message.edit_text(
        "Введи текст уведомления победителю.\n"
        "Плейсхолдер: <code>{account}</code>\n\n"
        "Пример:\n<code>🎉 Поздравляем!\n\nВаш аккаунт:\n{account}</code>",
        parse_mode="HTML",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(AdminStates.waiting_notify_text)
async def handle_notify_text(message: Message, config: Config, db: Database, state: FSMContext) -> None:
    if not _is_admin(config, message.from_user.id):
        return
    await db.set_setting("notify_text", message.text)
    await state.clear()
    await message.answer("✅ Текст уведомления сохранён.", reply_markup=settings_menu_kb())


@router.callback_query(F.data == "set_piarflow_steps")
async def cb_set_piarflow_steps(callback: CallbackQuery, config: Config, state: FSMContext) -> None:
    if not _is_admin(config, callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(AdminStates.waiting_piarflow_steps)
    await callback.message.edit_text(
        "🤖 <b>Настройка шагов @PiarFlowBot</b>\n\n"
        "После того как узнаешь флоу создания конкурса — введи шаги в формате JSON.\n\n"
        "Каждый шаг:\n"
        '<code>{"action": "send", "value": "/start", "wait": 2}</code>\n'
        '<code>{"action": "click", "value": "Создать конкурс", "wait": 2}</code>\n'
        '<code>{"action": "replace", "value": "{channel_id}", "wait": 2, "extract_link": true}</code>\n\n'
        "actions: <b>send</b> (текст), <b>click</b> (кнопка по тексту), <b>replace</b> (текст с подстановкой)\n"
        "extract_link: true — вытащить ссылку из последнего ответа бота\n\n"
        "Отправь <code>-</code> для сброса (режим обучения).",
        parse_mode="HTML",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(AdminStates.waiting_piarflow_steps)
async def handle_piarflow_steps(message: Message, config: Config, db: Database, state: FSMContext) -> None:
    if not _is_admin(config, message.from_user.id):
        return
    text = message.text.strip()
    if text == "-":
        await db.set_setting("piarflow_steps", "")
        await state.clear()
        await message.answer("✅ Сброшено. Включён режим обучения.", reply_markup=settings_menu_kb())
        return
    import json
    try:
        steps = json.loads(text)
        assert isinstance(steps, list)
        await db.set_setting("piarflow_steps", text)
        await state.clear()
        await message.answer(f"✅ Сохранено {len(steps)} шагов.", reply_markup=settings_menu_kb())
    except Exception:
        await message.answer(
            "❌ Неверный JSON. Проверь формат и попробуй снова.",
            reply_markup=cancel_kb(),
        )


# ── Logs ───────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin_logs")
async def cb_admin_logs(callback: CallbackQuery, config: Config, db: Database) -> None:
    if not _is_admin(config, callback.from_user.id):
        await callback.answer()
        return
    logs = await db.get_logs(20)
    if not logs:
        await callback.message.edit_text("Логов пока нет.", reply_markup=back_to_admin_kb())
        await callback.answer()
        return
    lines = [f"• {l['created_at'][:16]} [{l['action']}] {(l['details'] or '')[:60]}" for l in logs]
    await callback.message.edit_text("📋 Последние события:\n\n" + "\n".join(lines), reply_markup=back_to_admin_kb())
    await callback.answer()


# ── Tutorial management ────────────────────────────────────────────────────

@router.callback_query(F.data == "admin_tutorial")
async def cb_admin_tutorial(callback: CallbackQuery, config: Config, db: Database) -> None:
    if not _is_admin(config, callback.from_user.id):
        await callback.answer()
        return
    text = await db.get_setting("tutorial_text", "")
    video_id = await db.get_setting("tutorial_video_id", "")
    preview = (text[:100] + "…") if len(text) > 100 else text
    status = f"📝 Текст: {preview or '(не задан)'}\n🎥 Видео: {'✅ загружено' if video_id else '❌ нет'}"
    await callback.message.edit_text(
        f"📖 <b>Туториал</b>\n\n{status}",
        parse_mode="HTML",
        reply_markup=tutorial_admin_kb(has_video=bool(video_id)),
    )
    await callback.answer()


@router.callback_query(F.data == "set_tutorial_text")
async def cb_set_tutorial_text(callback: CallbackQuery, config: Config, state: FSMContext) -> None:
    if not _is_admin(config, callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(AdminStates.waiting_tutorial_text)
    await callback.message.edit_text(
        "✏️ Отправь новый текст туториала.\n\n"
        "Поддерживается HTML: <b>жирный</b>, <i>курсив</i>, <code>код</code>.",
        parse_mode="HTML",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(AdminStates.waiting_tutorial_text)
async def handle_tutorial_text(message: Message, config: Config, db: Database, state: FSMContext) -> None:
    if not _is_admin(config, message.from_user.id):
        return
    await db.set_setting("tutorial_text", message.text or "")
    await state.clear()
    await message.answer("✅ Текст туториала сохранён.", reply_markup=settings_menu_kb())


@router.callback_query(F.data == "set_tutorial_video")
async def cb_set_tutorial_video(callback: CallbackQuery, config: Config, state: FSMContext) -> None:
    if not _is_admin(config, callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(AdminStates.waiting_tutorial_video)
    await callback.message.edit_text(
        "🎥 Отправь видео для туториала.\n\n"
        "Это обычное видео (не документ). Оно будет показываться пользователям вместе с текстом.",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(AdminStates.waiting_tutorial_video)
async def handle_tutorial_video(message: Message, config: Config, db: Database, state: FSMContext) -> None:
    if not _is_admin(config, message.from_user.id):
        return
    if not message.video:
        await message.answer("❌ Пришли видео (не документ, не GIF).", reply_markup=cancel_kb())
        return
    await db.set_setting("tutorial_video_id", message.video.file_id)
    await state.clear()
    await message.answer("✅ Видео туториала сохранено.", reply_markup=settings_menu_kb())


@router.callback_query(F.data == "del_tutorial_video")
async def cb_del_tutorial_video(callback: CallbackQuery, config: Config, db: Database) -> None:
    if not _is_admin(config, callback.from_user.id):
        await callback.answer()
        return
    await db.set_setting("tutorial_video_id", "")
    await callback.message.edit_text("✅ Видео удалено.", reply_markup=settings_menu_kb())
    await callback.answer()


# ── Reviews URL management ─────────────────────────────────────────────────

@router.callback_query(F.data == "admin_reviews")
async def cb_admin_reviews(callback: CallbackQuery, config: Config, db: Database, state: FSMContext) -> None:
    if not _is_admin(config, callback.from_user.id):
        await callback.answer()
        return
    url = await db.get_setting("reviews_url", "")
    await callback.message.edit_text(
        f"⭐ <b>Ссылка отзывов</b>\n\n"
        f"Текущая: {url or '(не задана)'}\n\n"
        f"Отправь новую ссылку на канал с отзывами.\n"
        f"Отправь <code>-</code> чтобы убрать кнопку.",
        parse_mode="HTML",
        reply_markup=cancel_kb(),
    )
    await state.set_state(AdminStates.waiting_reviews_url)
    await callback.answer()


@router.message(AdminStates.waiting_reviews_url)
async def handle_reviews_url(message: Message, config: Config, db: Database, state: FSMContext) -> None:
    if not _is_admin(config, message.from_user.id):
        return
    val = "" if message.text.strip() == "-" else message.text.strip()
    await db.set_setting("reviews_url", val)
    await state.clear()
    await message.answer(
        f"✅ Ссылка отзывов {'убрана' if not val else f'сохранена: {val}'}",
        reply_markup=settings_menu_kb(),
    )


# ── Reviews channel management ────────────────────────────────────────────

@router.callback_query(F.data == "admin_reviews_channel")
async def cb_admin_reviews_channel(callback: CallbackQuery, config: Config, db: Database, state: FSMContext) -> None:
    if not _is_admin(config, callback.from_user.id):
        await callback.answer()
        return
    channel_id = await db.get_setting("reviews_channel_id", "")
    await callback.message.edit_text(
        f"📬 <b>Канал для публикации отзывов</b>\n\n"
        f"Текущий ID: <code>{channel_id or '(не задан)'}</code>\n\n"
        f"Отправь числовой ID канала (бот должен быть админом в нём).\n"
        f"Пример: <code>-1001234567890</code>\n\n"
        f"Отправь <code>-</code> чтобы отключить публикацию.",
        parse_mode="HTML",
        reply_markup=cancel_kb(),
    )
    await state.set_state(AdminStates.waiting_reviews_channel_id)
    await callback.answer()


@router.message(AdminStates.waiting_reviews_channel_id)
async def handle_reviews_channel_id(message: Message, config: Config, db: Database, state: FSMContext) -> None:
    if not _is_admin(config, message.from_user.id):
        return
    val = "" if message.text.strip() == "-" else message.text.strip()
    await db.set_setting("reviews_channel_id", val)
    await state.clear()
    await message.answer(
        f"✅ Канал отзывов {'отключён' if not val else f'задан: <code>{val}</code>'}",
        parse_mode="HTML",
        reply_markup=settings_menu_kb(),
    )


# ── Subscription management ────────────────────────────────────────────────

@router.callback_query(F.data == "admin_subscription")
async def cb_admin_subscription(callback: CallbackQuery, config: Config, db: Database) -> None:
    if not _is_admin(config, callback.from_user.id):
        await callback.answer()
        return
    val = await db.get_setting("require_subscription", "0")
    enabled = val == "1"
    status = "🟢 <b>Включена</b>" if enabled else "🔴 <b>Выключена</b>"
    await callback.message.edit_text(
        f"🔔 <b>Обязательная подписка</b>\n\n"
        f"Статус: {status}\n\n"
        f"Канал: <code>{config.CHANNEL_ID}</code>",
        parse_mode="HTML",
        reply_markup=subscription_admin_kb(enabled=enabled),
    )
    await callback.answer()


@router.callback_query(F.data == "toggle_subscription")
async def cb_toggle_subscription(callback: CallbackQuery, config: Config, db: Database) -> None:
    if not _is_admin(config, callback.from_user.id):
        await callback.answer()
        return
    val = await db.get_setting("require_subscription", "0")
    new_val = "0" if val == "1" else "1"
    await db.set_setting("require_subscription", new_val)
    enabled = new_val == "1"
    status = "🟢 <b>Включена</b>" if enabled else "🔴 <b>Выключена</b>"
    await callback.message.edit_text(
        f"🔔 <b>Обязательная подписка</b>\n\n"
        f"Статус: {status}\n\n"
        f"Канал: <code>{config.CHANNEL_ID}</code>",
        parse_mode="HTML",
        reply_markup=subscription_admin_kb(enabled=enabled),
    )
    await callback.answer("✅ Сохранено")


# ── Broadcast ──────────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin_broadcast")
async def cb_admin_broadcast(callback: CallbackQuery, config: Config, state: FSMContext) -> None:
    if not _is_admin(config, callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(AdminStates.waiting_broadcast_msg)
    await callback.message.edit_text(
        "📢 <b>Рассылка</b>\n\n"
        "Отправь сообщение которое нужно разослать всем пользователям.\n"
        "Поддерживаются: текст, фото, видео, документ.",
        parse_mode="HTML",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(AdminStates.waiting_broadcast_msg)
async def handle_broadcast_msg(message: Message, config: Config, db: Database, state: FSMContext) -> None:
    if not _is_admin(config, message.from_user.id):
        return
    users = await db.get_all_users()
    await state.update_data(
        broadcast_chat_id=message.chat.id,
        broadcast_msg_id=message.message_id,
    )
    await state.set_state(None)
    count = len(users)
    await message.answer(
        f"👆 Предпросмотр выше.\n\n"
        f"Рассылка будет отправлена <b>{count} пользователям</b>.\n"
        f"Подтверждаешь?",
        parse_mode="HTML",
        reply_markup=broadcast_confirm_kb(),
    )


@router.callback_query(F.data == "confirm_broadcast")
async def cb_confirm_broadcast(
    callback: CallbackQuery, config: Config, db: Database, state: FSMContext
) -> None:
    import asyncio as _asyncio
    if not _is_admin(config, callback.from_user.id):
        await callback.answer()
        return
    data = await state.get_data()
    src_chat = data.get("broadcast_chat_id")
    src_msg = data.get("broadcast_msg_id")
    if not src_chat or not src_msg:
        await callback.answer("Нет сообщения для рассылки.", show_alert=True)
        return

    await callback.message.edit_text(f"{E_LOADING} Рассылка запущена...", parse_mode="HTML")
    await callback.answer()

    users = await db.get_all_users()
    ok, fail = 0, 0
    for user in users:
        try:
            await callback.bot.copy_message(
                chat_id=user.tg_id,
                from_chat_id=src_chat,
                message_id=src_msg,
            )
            ok += 1
        except Exception as exc:
            if isinstance(exc, _asyncio.CancelledError):
                raise
            fail += 1
        await _asyncio.sleep(0.05)

    try:
        await callback.message.answer(
            f"{E_BROADCAST} <b>Рассылка завершена</b>\n\n"
            f"{E_CHECK} Доставлено: <b>{ok}</b>\n"
            f"{E_CROSS} Ошибок: <b>{fail}</b>",
            parse_mode="HTML",
            reply_markup=back_to_admin_kb(),
        )
    except Exception:
        pass
    await db.add_log("broadcast", f"ok={ok} fail={fail}", callback.from_user.id)
    await state.clear()


# ── Promo codes management ─────────────────────────────────────────────────

@router.callback_query(F.data == "admin_promos")
async def cb_admin_promos(callback: CallbackQuery, config: Config, db: Database) -> None:
    if not _is_admin(config, callback.from_user.id):
        await callback.answer()
        return
    free = await db.get_free_promo_count()
    promos = await db.get_all_promos(5)
    issued_count = sum(1 for p in await db.get_all_promos(1000) if p.status == "issued")
    text = (
        f"🎟 <b>Промокоды @feAutoSenderbot</b>\n\n"
        f"✅ Свободных: <b>{free}</b>\n"
        f"📤 Выдано: <b>{issued_count}</b>\n\n"
        f"Промокоды выдаются пользователям при достижении 20 и 30 участников в конкурсе."
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=promos_admin_kb())
    await callback.answer()


@router.callback_query(F.data == "promos_stats")
async def cb_promos_stats(callback: CallbackQuery, config: Config, db: Database) -> None:
    if not _is_admin(config, callback.from_user.id):
        await callback.answer()
        return
    promos = await db.get_all_promos(20)
    if not promos:
        await callback.message.edit_text("Промокодов нет.", reply_markup=promos_admin_kb())
        await callback.answer()
        return
    lines = []
    for p in promos:
        icon = "✅" if p.status == "free" else "📤"
        issued_info = f" → {p.issued_to}" if p.issued_to else ""
        lines.append(f"{icon} <code>{p.code}</code>{issued_info}")
    text = "🎟 <b>Последние промокоды:</b>\n\n" + "\n".join(lines)
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=promos_admin_kb())
    await callback.answer()


@router.callback_query(F.data == "add_promo_codes")
async def cb_add_promo_codes(callback: CallbackQuery, config: Config, state: FSMContext) -> None:
    if not _is_admin(config, callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(AdminStates.waiting_promo_codes)
    await callback.message.edit_text(
        "🎟 <b>Добавление промокодов</b>\n\n"
        "Отправь промокоды — по одному на строку:\n\n"
        "<code>PROMO2024\nCODE12345\nABC-XYZ-99</code>",
        parse_mode="HTML",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(AdminStates.waiting_promo_codes)
async def handle_promo_codes(message: Message, config: Config, db: Database, state: FSMContext) -> None:
    if not _is_admin(config, message.from_user.id):
        return
    codes = [line.strip() for line in (message.text or "").splitlines() if line.strip()]
    if not codes:
        await message.answer("❌ Нет кодов. Отправь коды по одному на строку.", reply_markup=cancel_kb())
        return
    added = await db.add_promo_codes(codes, message.from_user.id)
    await state.clear()
    await db.add_log("promos_added", f"count={added}", message.from_user.id)
    free_total = await db.get_free_promo_count()
    await message.answer(
        f"✅ Добавлено промокодов: <b>{added}</b>\n"
        f"Свободных всего: <b>{free_total}</b>",
        parse_mode="HTML",
        reply_markup=promos_admin_kb(),
    )


# ── Schedule management ────────────────────────────────────────────────────

@router.callback_query(F.data == "admin_schedule")
async def cb_admin_schedule(callback: CallbackQuery, config: Config, db: Database) -> None:
    if not _is_admin(config, callback.from_user.id):
        await callback.answer()
        return
    start_time = await db.get_setting("contest_start_time", "")
    end_time = await db.get_setting("contest_end_time", "")
    pending = await db.get_pending_contests()
    active = await db.get_active_contests()
    text = (
        f"🕐 <b>Расписание конкурсов</b>\n\n"
        f"Запуск:       <b>{start_time or '—'}</b>  (по Киеву)\n"
        f"Завершение: <b>{end_time or '—'}</b>  (по Киеву)\n\n"
        f"В очереди: <b>{len(pending)}</b> | Активных: <b>{len(active)}</b>\n\n"
        f"Каждый день в указанное время бот:\n"
        f"• запускает все ожидающие конкурсы\n"
        f"• завершает все активные, выдаёт награды по тирам и шлёт уведомления"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=schedule_kb(start_time, end_time))
    await callback.answer()


@router.callback_query(F.data == "set_start_time")
async def cb_set_start_time(callback: CallbackQuery, config: Config, state: FSMContext) -> None:
    if not _is_admin(config, callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(AdminStates.waiting_start_time)
    await callback.message.edit_text(
        "⏰ Введи время <b>запуска</b> конкурсов (UTC):\n\n"
        "Формат: <code>ЧЧ:ММ</code>  (например <code>09:00</code>)\n\n"
        "Отправь <code>-</code> чтобы отключить автозапуск.",
        parse_mode="HTML",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(AdminStates.waiting_start_time)
async def handle_start_time(message: Message, config: Config, db: Database, state: FSMContext) -> None:
    if not _is_admin(config, message.from_user.id):
        return
    val = message.text.strip()
    if val == "-":
        await db.set_setting("contest_start_time", "")
        await db.set_setting("scheduler_last_launch_date", "")
        await state.clear()
        await message.answer("✅ Автозапуск отключён.", reply_markup=settings_menu_kb())
        return
    parts = val.split(":")
    if len(parts) != 2 or not all(p.isdigit() for p in parts) or not (0 <= int(parts[0]) < 24) or not (0 <= int(parts[1]) < 60):
        await message.answer("❌ Неверный формат. Пример: <code>09:00</code>", parse_mode="HTML", reply_markup=cancel_kb())
        return
    clean = f"{int(parts[0]):02d}:{int(parts[1]):02d}"
    await db.set_setting("contest_start_time", clean)
    await db.set_setting("scheduler_last_launch_date", "")
    await state.clear()
    await message.answer(f"✅ Время запуска: <b>{clean}</b> UTC", parse_mode="HTML", reply_markup=settings_menu_kb())


@router.callback_query(F.data == "set_end_time")
async def cb_set_end_time(callback: CallbackQuery, config: Config, state: FSMContext) -> None:
    if not _is_admin(config, callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(AdminStates.waiting_end_time)
    await callback.message.edit_text(
        "⏰ Введи время <b>завершения</b> конкурсов (UTC):\n\n"
        "Формат: <code>ЧЧ:ММ</code>  (например <code>21:00</code>)\n\n"
        "Отправь <code>-</code> чтобы отключить автозавершение.",
        parse_mode="HTML",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(AdminStates.waiting_end_time)
async def handle_end_time(message: Message, config: Config, db: Database, state: FSMContext) -> None:
    if not _is_admin(config, message.from_user.id):
        return
    val = message.text.strip()
    if val == "-":
        await db.set_setting("contest_end_time", "")
        await db.set_setting("scheduler_last_close_date", "")
        await state.clear()
        await message.answer("✅ Автозавершение отключено.", reply_markup=settings_menu_kb())
        return
    parts = val.split(":")
    if len(parts) != 2 or not all(p.isdigit() for p in parts) or not (0 <= int(parts[0]) < 24) or not (0 <= int(parts[1]) < 60):
        await message.answer("❌ Неверный формат. Пример: <code>21:00</code>", parse_mode="HTML", reply_markup=cancel_kb())
        return
    clean = f"{int(parts[0]):02d}:{int(parts[1]):02d}"
    await db.set_setting("contest_end_time", clean)
    await db.set_setting("scheduler_last_close_date", "")
    await state.clear()
    await message.answer(f"✅ Время завершения: <b>{clean}</b> UTC", parse_mode="HTML", reply_markup=settings_menu_kb())


# ── Userbot auth ───────────────────────────────────────────────────────────

@router.message(Command("auth"))
async def cmd_auth(message: Message, config: Config, state: FSMContext) -> None:
    if not _is_admin(config, message.from_user.id):
        return
    await state.set_state(AdminStates.auth_phone)
    await message.answer(
        "📱 Авторизация userbot\n\nВведи номер телефона:\n<code>+79001234567</code>",
        parse_mode="HTML",
    )


@router.message(AdminStates.auth_phone)
async def handle_auth_phone(message: Message, config: Config, state: FSMContext, manager) -> None:
    if not _is_admin(config, message.from_user.id):
        return
    try:
        await manager.send_code(message.text.strip())
        await state.update_data(phone=message.text.strip())
        await state.set_state(AdminStates.auth_code)
        await message.answer("Код отправлен. Введи код из Telegram:")
    except Exception as exc:
        await message.answer(f"Ошибка: {exc}")


@router.message(AdminStates.auth_code)
async def handle_auth_code(
    message: Message, config: Config, db: Database, state: FSMContext, manager, monitor
) -> None:
    if not _is_admin(config, message.from_user.id):
        return
    try:
        session_str = await manager.sign_in(message.text.strip())
        await _finish_auth(message, config, db, state, manager, monitor, session_str)
    except SessionPasswordNeededError:
        await state.set_state(AdminStates.auth_password)
        await message.answer("Введи пароль двухфакторной аутентификации:")
    except PhoneCodeInvalidError:
        await message.answer("Неверный код. Попробуй ещё раз:")
    except Exception as exc:
        await message.answer(f"Ошибка: {exc}")
        await state.clear()


@router.message(AdminStates.auth_password)
async def handle_auth_password(
    message: Message, config: Config, db: Database, state: FSMContext, manager, monitor
) -> None:
    if not _is_admin(config, message.from_user.id):
        return
    try:
        session_str = await manager.sign_in_2fa(message.text.strip())
        await _finish_auth(message, config, db, state, manager, monitor, session_str)
    except Exception as exc:
        await message.answer(f"Ошибка: {exc}")
        await state.clear()


async def _finish_auth(message, config, db, state, manager, monitor, session_str: str) -> None:
    config.USERBOT_SESSION = session_str
    manager._config = config
    await manager._connect()
    if monitor:
        manager._monitor = monitor
    await state.clear()
    await db.add_log("userbot_authorized", f"admin={message.from_user.id}", message.from_user.id)
    await message.answer(
        f"✅ Userbot авторизован и запущен!\n\n"
        f"Сохрани в .env:\n<code>USERBOT_SESSION={session_str}</code>",
        parse_mode="HTML",
    )


# ── Ads management ─────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin_ads")
async def cb_admin_ads(callback: CallbackQuery, config: Config, db: Database, state: FSMContext) -> None:
    if not _is_admin(config, callback.from_user.id):
        await callback.answer()
        return
    await state.clear()
    items = await db.get_ads_items()
    text = "📢 <b>Управление рекламой</b>\n\nНажми ❌ чтобы удалить элемент."
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=admin_ads_kb(items))
    await callback.answer()


@router.callback_query(F.data.startswith("admin_add_ads:"))
async def cb_admin_add_ads(callback: CallbackQuery, config: Config, state: FSMContext) -> None:
    if not _is_admin(config, callback.from_user.id):
        await callback.answer()
        return
    ads_type = callback.data.split(":")[1]
    await state.set_state(AdminStates.waiting_ads_name)
    await state.update_data(ads_type=ads_type)
    label = "проекта" if ads_type == "project" else "спонсора"
    await callback.message.edit_text(
        f"Введи название {label}:", reply_markup=cancel_kb()
    )
    await callback.answer()


@router.message(AdminStates.waiting_ads_name)
async def handle_ads_name(message: Message, config: Config, state: FSMContext) -> None:
    if not _is_admin(config, message.from_user.id):
        return
    await state.update_data(ads_name=message.text.strip())
    await state.set_state(AdminStates.waiting_ads_text)
    await message.answer("Введи текст (будет показан пользователям при нажатии на кнопку):", reply_markup=cancel_kb())


@router.message(AdminStates.waiting_ads_text)
async def handle_ads_text(message: Message, config: Config, db: Database, state: FSMContext) -> None:
    if not _is_admin(config, message.from_user.id):
        return
    data = await state.get_data()
    await db.add_ads_item(data["ads_type"], data["ads_name"], message.text.strip())
    await state.clear()
    items = await db.get_ads_items()
    await message.answer("✅ Добавлено.", reply_markup=admin_ads_kb(items))


@router.callback_query(F.data.startswith("delete_ads:"))
async def cb_delete_ads(callback: CallbackQuery, config: Config, db: Database) -> None:
    if not _is_admin(config, callback.from_user.id):
        await callback.answer()
        return
    item_id = int(callback.data.split(":")[1])
    await db.delete_ads_item(item_id)
    items = await db.get_ads_items()
    text = "📢 <b>Управление рекламой</b>\n\nНажми ❌ чтобы удалить элемент."
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=admin_ads_kb(items))
    await callback.answer("✅ Удалено")
