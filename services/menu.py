# services/menu.py
"""
Модуль управления меню Telegram бота (система таргетов) - единое сообщение.

Этот модуль содержит функции для:
- Генерации inline-клавиатур для меню с таргетами.
- Обновления меню в едином сообщении.
- Безопасного редактирования с fallback на новое сообщение.

Основные функции:
- update_menu: Обновляет меню в том же сообщении.
- safe_edit_menu: Безопасное редактирование с обработкой ошибок.
- config_action_keyboard: Генерирует клавиатуру для действий в меню.
"""

# --- Сторонние библиотеки ---
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from aiogram.exceptions import TelegramBadRequest
import logging

# --- Внутренние библиотеки ---
from services.config import get_valid_config, format_config_summary

logger = logging.getLogger(__name__)


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


async def safe_edit_menu(message: Message, text: str, reply_markup: InlineKeyboardMarkup = None) -> bool:
    """
    Безопасно редактирует сообщение с меню. Если редактирование не удается,
    отправляет новое сообщение.

    :param message: Объект сообщения для редактирования
    :param text: Новый текст сообщения
    :param reply_markup: Новая клавиатура
    :return: True если успешно отредактировано, False если отправлено новое
    """
    try:
        await message.edit_text(text, reply_markup=reply_markup, disable_web_page_preview=True)
        return True
    except TelegramBadRequest as e:
        # Если не можем отредактировать, отправляем новое сообщение
        if "message is not modified" in str(e).lower():
            # Сообщение не изменилось, это нормально
            return True
        elif "message to edit not found" in str(e).lower() or "message can't be edited" in str(e).lower():
            # Сообщение не найдено или не может быть отредактировано
            logger.warning(f"Не удалось отредактировать сообщение: {e}. Отправляем новое.")
            try:
                await message.answer(text, reply_markup=reply_markup, disable_web_page_preview=True)
            except Exception as send_error:
                logger.error(f"Ошибка при отправке нового сообщения: {send_error}")
            return False
        else:
            logger.error(f"Неожиданная ошибка при редактировании: {e}")
            return False
    except Exception as e:
        logger.error(f"Ошибка при редактировании сообщения: {e}")
        try:
            await message.answer(text, reply_markup=reply_markup, disable_web_page_preview=True)
        except Exception as send_error:
            logger.error(f"Ошибка при отправке fallback сообщения: {send_error}")
        return False


async def update_menu(bot: Bot, chat_id: int, user_id: int, message_id: int) -> None:
    """
    Обновляет главное меню в том же сообщении.

    :param bot: Объект бота
    :param chat_id: ID чата
    :param user_id: ID пользователя
    :param message_id: ID сообщения для редактирования
    """
    config = await get_valid_config()
    text = format_config_summary(config, user_id)
    keyboard = config_action_keyboard(config.get("ACTIVE", False))

    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            # Сообщение не изменилось, это нормально
            pass
        elif "message to edit not found" in str(e).lower() or "message can't be edited" in str(e).lower():
            # Сообщение не найдено, отправляем новое
            logger.warning(f"Сообщение для редактирования не найдено. Отправляем новое.")
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=keyboard,
                disable_web_page_preview=True
            )
        else:
            logger.error(f"Ошибка при обновлении меню: {e}")
    except Exception as e:
        logger.error(f"Неожиданная ошибка при обновлении меню: {e}")


async def send_main_menu(bot: Bot, chat_id: int, user_id: int) -> int:
    """
    Отправляет главное меню (используется только при первом запуске).

    :param bot: Объект бота
    :param chat_id: ID чата
    :param user_id: ID пользователя
    :return: ID отправленного сообщения
    """
    config = await get_valid_config()
    text = format_config_summary(config, user_id)
    keyboard = config_action_keyboard(config.get("ACTIVE", False))

    sent = await bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=keyboard,
        disable_web_page_preview=True
    )
    return sent.message_id