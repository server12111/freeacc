from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.constants import (
    I_BOX, I_CHART_UP, I_COIN, I_SETTINGS, I_BROADCAST, I_FILE,
    I_GIFT, I_WALLET, I_INFO, I_BELL, I_EYE, I_WRITE, I_CLOCK,
    I_CHECK, I_CROSS, I_LINK, I_RELOAD, I_PEOPLE, I_PENCIL, I_TRASH,
    I_MEDIA,
)

_S_OK  = "success"  # green
_S_BAD = "danger"   # red
_S_PRI = "primary"  # blue


def _btn(text: str, callback_data: str, style: str = "", icon: str = "") -> InlineKeyboardButton:
    kwargs: dict = {"text": text, "callback_data": callback_data}
    if style:
        kwargs["style"] = style
    if icon:
        kwargs["icon_custom_emoji_id"] = icon
    return InlineKeyboardButton(**kwargs)


def _url_btn(text: str, url: str, style: str = "", icon: str = "") -> InlineKeyboardButton:
    kwargs: dict = {"text": text, "url": url}
    if style:
        kwargs["style"] = style
    if icon:
        kwargs["icon_custom_emoji_id"] = icon
    return InlineKeyboardButton(**kwargs)


def main_menu_kb(has_contest: bool = False, reviews_url: str = "") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if has_contest:
        builder.row(_btn("Мой прогресс", "my_progress", _S_PRI, I_CHART_UP))
    else:
        builder.row(_btn("Получить бесплатно", "get_account", _S_OK, I_GIFT))
    builder.row(
        _btn("Купить · $0.5", "buy_account", _S_PRI, I_WALLET),
        _btn("Как работает", "tutorial", _S_PRI, I_INFO),
    )
    builder.row(_btn("Рефералы", "referrals", _S_PRI, I_PEOPLE))
    if reviews_url:
        builder.row(
            _btn("Реклама", "ads", _S_PRI, I_BROADCAST),
            _url_btn("Отзывы", reviews_url, _S_PRI),
        )
    else:
        builder.row(_btn("Реклама", "ads", _S_PRI, I_BROADCAST))
    return builder.as_markup()


def subscription_wall_kb(channel_id: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    try:
        cid = int(channel_id)
        chan_link = f"https://t.me/c/{str(abs(cid))[3:]}"
    except Exception:
        chan_link = "https://t.me"
    builder.row(_url_btn("Перейти в канал", chan_link, _S_OK, I_BROADCAST))
    builder.row(_btn("Я подписался", "check_subscription", _S_OK, I_CHECK))
    return builder.as_markup()


def tutorial_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(_btn("◁ Назад", "back_to_menu"))
    return builder.as_markup()


def confirm_create_contest_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(_btn("Создать мой конкурс", "confirm_create_contest", _S_OK, I_GIFT))
    return builder.as_markup()


def check_payment_kb(invoice_id: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        _btn("Я оплатил", f"check_payment:{invoice_id}", _S_OK, I_CHECK),
        _btn("Отмена", "cancel_payment", _S_BAD, I_CROSS),
    )
    return builder.as_markup()


def get_code_kb(pool_id: int, retry: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if retry:
        builder.row(_btn("Получить новый код", f"get_code:{pool_id}", _S_PRI, I_RELOAD))
    else:
        builder.row(_btn("Получить код входа", f"get_code:{pool_id}", _S_OK, I_LINK))
    return builder.as_markup()


# ── Admin keyboards ────────────────────────────────────────────────────────

def promos_admin_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.add(
        _btn("Добавить промокоды", "add_promo_codes", _S_OK, I_COIN),
        _btn("Статистика", "promos_stats", _S_PRI, I_CHART_UP),
    )
    builder.adjust(2)
    builder.row(_btn("◁ Назад", "admin_menu"))
    return builder.as_markup()


def admin_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.add(
        _btn("Аккаунты", "admin_accounts", _S_PRI, I_BOX),
        _btn("Конкурсы", "admin_contests", _S_PRI, I_CHART_UP),
        _btn("Промокоды", "admin_promos", _S_PRI, I_COIN),
        _btn("Настройки", "admin_settings", _S_PRI, I_SETTINGS),
        _btn("Рассылка", "admin_broadcast", _S_PRI, I_BROADCAST),
        _btn("Логи", "admin_logs", _S_PRI, I_FILE),
        _btn("Реклама", "admin_ads", _S_PRI, I_BROADCAST),
    )
    builder.adjust(2)
    return builder.as_markup()


def back_to_admin_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(_btn("◁ Назад", "admin_menu"))
    return builder.as_markup()


def accounts_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.add(
        _btn("Добавить аккаунт", "add_accounts", _S_OK, I_BOX),
        _btn("Статистика пула", "accounts_stats", _S_PRI, I_CHART_UP),
        _btn("История выдач", "accounts_history", _S_PRI, I_FILE),
    )
    builder.adjust(2)
    builder.row(_btn("◁ Назад", "admin_menu"))
    return builder.as_markup()


def contests_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(_btn("Список конкурсов", "list_contests", _S_PRI, I_FILE))
    builder.row(_btn("◁ Назад", "admin_menu"))
    return builder.as_markup()


def contest_actions_kb(contest_id: int, status: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if status == "active":
        builder.row(_btn("Завершить", f"contest_finish:{contest_id}", _S_OK, I_CHECK))
    builder.row(_btn("◁ Назад", "list_contests"))
    return builder.as_markup()


def warmup_bot_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(_url_btn("Прогреть аккаунт", "https://t.me/SrvnkWarmUpAccBot", _S_OK))
    return builder.as_markup()


def referral_kb(bot_username: str, user_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(_btn("Скопировать ссылку", f"copy_ref:{user_id}:{bot_username}", _S_PRI, I_LINK))
    builder.row(_btn("◁ Назад", "back_to_menu"))
    return builder.as_markup()


def try_again_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(_btn("Попробовать снова", "get_account", _S_OK, I_GIFT))
    return builder.as_markup()


def back_to_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(_btn("◁ В меню", "back_to_menu"))
    return builder.as_markup()


def ads_main_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        _btn("📁 Наши проекты", "ads_section:project", _S_PRI),
        _btn("💼 Спонсоры",     "ads_section:sponsor",  _S_PRI),
    )
    builder.row(_btn("◁ В меню", "back_to_menu"))
    return builder.as_markup()


def ads_section_kb(items: list, section: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in items:
        builder.row(_btn(item.name, f"ads_item:{item.id}", _S_PRI))
    builder.row(_btn("◁ Назад", "ads"))
    return builder.as_markup()


def ads_item_kb(section: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(_btn("◁ Назад", f"ads_section:{section}"))
    return builder.as_markup()


def admin_ads_kb(items: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(_btn("➕ Добавить проект", "admin_add_ads:project", _S_OK))
    builder.row(_btn("➕ Добавить спонсора", "admin_add_ads:sponsor", _S_OK))
    for item in items:
        prefix = "📁" if item.type == "project" else "💼"
        builder.row(_btn(f"❌ {prefix} {item.name}", f"delete_ads:{item.id}", _S_BAD))
    builder.row(_btn("◁ Назад", "admin_menu"))
    return builder.as_markup()


def progress_kb(link: str = "") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if link:
        builder.row(_url_btn("Открыть конкурс", link, _S_PRI, I_LINK))
    builder.row(_btn("◁ В меню", "back_to_menu"))
    return builder.as_markup()


def review_request_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.add(
        _btn("Написать отзыв", "write_review", _S_OK, I_WRITE),
        _btn("Пропустить", "skip_review"),
    )
    builder.adjust(2)
    return builder.as_markup()


def cancel_review_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(_btn("◁ Отмена", "skip_review"))
    return builder.as_markup()


def schedule_kb(start_time: str = "", end_time: str = "") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    start_label = f"Запуск: {start_time}" if start_time else "Задать время запуска"
    end_label = f"Завершение: {end_time}" if end_time else "Задать время завершения"
    builder.add(
        _btn(start_label, "set_start_time", _S_PRI, I_CLOCK),
        _btn(end_label, "set_end_time", _S_PRI, I_CLOCK),
    )
    builder.adjust(1)
    builder.row(_btn("◁ Назад", "admin_settings"))
    return builder.as_markup()


def settings_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.add(
        _btn("Расписание конкурсов", "admin_schedule", _S_PRI, I_CLOCK),
        _btn("Туториал", "admin_tutorial", _S_PRI, I_INFO),
        _btn("Отзывы — ссылка", "admin_reviews", _S_PRI),
        _btn("Канал отзывов", "admin_reviews_channel", _S_PRI, I_WRITE),
        _btn("Обяз. подписка", "admin_subscription", _S_PRI, I_BELL),
        _btn("Regex-паттерн", "set_parse_pattern", _S_PRI, I_EYE),
        _btn("Текст уведомления", "set_notify_text", _S_PRI, I_WRITE),
    )
    builder.adjust(2)
    builder.row(_btn("◁ Назад", "admin_menu"))
    return builder.as_markup()


def tutorial_admin_kb(has_video: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(_btn("Изменить текст", "set_tutorial_text", _S_PRI, I_PENCIL))
    if has_video:
        builder.add(
            _btn("Заменить видео", "set_tutorial_video", _S_PRI, I_MEDIA),
            _btn("Удалить видео", "del_tutorial_video", _S_BAD, I_TRASH),
        )
        builder.adjust(2)
    else:
        builder.row(_btn("Загрузить видео", "set_tutorial_video", _S_PRI, I_MEDIA))
    builder.row(_btn("◁ Назад", "admin_settings"))
    return builder.as_markup()


def subscription_admin_kb(enabled: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if enabled:
        builder.row(_btn("Выключить", "toggle_subscription", _S_BAD, I_CROSS))
    else:
        builder.row(_btn("Включить", "toggle_subscription", _S_OK, I_CHECK))
    builder.row(_btn("◁ Назад", "admin_settings"))
    return builder.as_markup()


def broadcast_confirm_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.add(
        _btn("Начать рассылку", "confirm_broadcast", _S_OK, I_BROADCAST),
        _btn("Отмена", "admin_menu", _S_BAD, I_CROSS),
    )
    builder.adjust(2)
    return builder.as_markup()


def cancel_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(_btn("Отмена", "admin_menu", _S_BAD, I_CROSS))
    return builder.as_markup()


def confirm_finish_kb(contest_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.add(
        _btn("Да", f"contest_finish_confirm:{contest_id}", _S_OK, I_CHECK),
        _btn("Отмена", f"contest_detail:{contest_id}", _S_BAD, I_CROSS),
    )
    builder.adjust(2)
    return builder.as_markup()
