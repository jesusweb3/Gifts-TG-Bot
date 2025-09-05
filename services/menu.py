# services/menu.py
"""
Модуль управления меню Telegram бота (система таргетов).

Этот модуль содержит функции для:
- Генерации inline-клавиатур для меню с таргетами.
- Обновления, отправки и удаления меню в чате.
- Сохранения и получения ID последнего сообщения меню.

Основные функции:
- update_menu: Обновляет меню в чате.
- send_menu: Отправляет новое меню в чат.
- delete_menu: Удаляет предыдущее меню.
- config_action_keyboard: Генерирует клавиатуру для действий в меню.
"""

# --- Сторонние библиотеки ---
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest

# --- Внутренние библиотеки ---
from services.config import load_config, save_config, get_valid_config, format_config_summary

async def update_last_menu_message_id(message_id: int) -> None:
    """
    Сохраняет id последнего сообщения с меню в конфиг.
    """
    config = await load_config()
    config["LAST_MENU_MESSAGE_ID"] = message_id
    await save_config(config)


async def get_last_menu_message_id() -> int | None:
    """
    Возвращает id последнего отправленного сообщения меню.
    """
    config = await load_config()
    return config.get("LAST_MENU_MESSAGE_ID")


def config_action_keyboard(active: bool) -> InlineKeyboardMarkup:
    """
    Генерирует inline-клавиатуру для меню с действиями (система таргетов).
    """
    toggle_text = "🔴 Выключить" if active else "🟢 Включить"
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=toggle_text, callback_data="toggle_active"),
            InlineKeyboardButton(text="🎯 Таргеты", callback_data="targets_menu")
        ],
        [
            InlineKeyboardButton(text="📥 Получатель", callback_data="recipient_menu"),
            InlineKeyboardButton(text="📤 Отправитель", callback_data="sender_menu")
        ]
    ])


async def update_menu(bot: Bot, chat_id: int, user_id: int, message_id: int) -> None:
    """
    Обновляет меню в чате: удаляет предыдущее и отправляет новое.
    """
    config = await get_valid_config()
    await delete_menu(bot=bot, chat_id=chat_id, current_message_id=message_id)
    await send_menu(bot=bot, chat_id=chat_id, config=config, text=format_config_summary(config, user_id))


async def delete_menu(bot: Bot, chat_id: int, current_message_id: int = None) -> None:
    """
    Удаляет последнее сообщение с меню, если оно отличается от текущего.
    Упрощенная версия - игнорирует большинство ошибок.
    """
    last_menu_message_id = await get_last_menu_message_id()
    if last_menu_message_id and last_menu_message_id != current_message_id:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=last_menu_message_id)
        except TelegramBadRequest:
            # Игнорируем ошибки удаления - сообщение могло быть уже удалено или устареть
            pass
        except Exception:
            # Игнорируем все остальные ошибки
            pass


async def send_menu(bot: Bot, chat_id: int, config: dict, text: str) -> int:
    """
    Отправляет новое меню в чат и обновляет id последнего сообщения.
    """
    sent = await bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=config_action_keyboard(config.get("ACTIVE"))
    )
    await update_last_menu_message_id(sent.message_id)
    return sent.message_id