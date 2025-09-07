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
    logger.debug(f"🎛️ МЕНЮ: Генерация клавиатуры для {'активной' if active else 'неактивной'} системы")

    toggle_text = "🔴 Выключить" if active else "🟢 Включить"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=toggle_text, callback_data="toggle_active"),
            InlineKeyboardButton(text="🎯 Таргеты", callback_data="targets_menu")
        ],
        [
            InlineKeyboardButton(text="📥 Получатель", callback_data="recipient_menu"),
            InlineKeyboardButton(text="📤 Отправитель", callback_data="sender_menu")
        ]
    ])

    logger.debug(f"🎛️ МЕНЮ: Клавиатура сгенерирована с кнопкой '{toggle_text}'")
    return keyboard


async def safe_edit_menu(message: Message, text: str, reply_markup: InlineKeyboardMarkup = None) -> bool:
    """
    Безопасно редактирует сообщение с меню. Если редактирование не удается,
    отправляет новое сообщение.

    :param message: Объект сообщения для редактирования
    :param text: Новый текст сообщения
    :param reply_markup: Новая клавиатура
    :return: True если успешно отредактировано, False если отправлено новое
    """
    message_id = message.message_id
    chat_id = message.chat.id

    logger.debug(f"🔄 МЕНЮ: Попытка редактирования сообщения ID {message_id} в чате {chat_id}")

    try:
        await message.edit_text(text, reply_markup=reply_markup, disable_web_page_preview=True)
        logger.debug(f"✅ МЕНЮ: Сообщение ID {message_id} успешно отредактировано")
        return True
    except TelegramBadRequest as e:
        error_msg = str(e).lower()

        # Если не можем отредактировать, отправляем новое сообщение
        if "message is not modified" in error_msg:
            # Сообщение не изменилось, это нормально
            logger.debug(f"ℹ️ МЕНЮ: Сообщение ID {message_id} не изменилось")
            return True
        elif "message to edit not found" in error_msg or "message can't be edited" in error_msg:
            # Сообщение не найдено или не может быть отредактировано
            logger.warning(f"⚠️ МЕНЮ: Не удалось отредактировать сообщение ID {message_id}: {e}")

            try:
                new_message = await message.answer(text, reply_markup=reply_markup, disable_web_page_preview=True)
                logger.info(f"✅ МЕНЮ: Новое сообщение ID {new_message.message_id} отправлено")
            except Exception as send_error:
                logger.error(f"❌ МЕНЮ: Ошибка при отправке нового сообщения: {send_error}")
            return False
        else:
            logger.error(f"❌ МЕНЮ: Неожиданная ошибка при редактировании сообщения ID {message_id}: {e}")
            return False
    except Exception as e:
        logger.error(f"💥 МЕНЮ: Критическая ошибка при редактировании сообщения ID {message_id}: {e}")
        try:
            new_message = await message.answer(text, reply_markup=reply_markup, disable_web_page_preview=True)
            logger.info(f"✅ МЕНЮ: Fallback сообщение ID {new_message.message_id} отправлено")
        except Exception as send_error:
            logger.error(f"❌ МЕНЮ: Критическая ошибка fallback отправки: {send_error}")
        return False


async def update_menu(bot: Bot, chat_id: int, user_id: int, message_id: int) -> None:
    """
    Обновляет главное меню в том же сообщении.

    :param bot: Объект бота
    :param chat_id: ID чата
    :param user_id: ID пользователя
    :param message_id: ID сообщения для редактирования
    """
    try:
        config = await get_valid_config()
        text = format_config_summary(config, user_id)
        keyboard = config_action_keyboard(config.get("ACTIVE", False))

        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )

    except TelegramBadRequest as e:
        error_msg = str(e).lower()

        if "message is not modified" in error_msg:
            # Сообщение не изменилось, это нормально
            logger.debug(f"ℹ️ МЕНЮ: Содержимое главного меню не изменилось (ID {message_id})")
        elif "message to edit not found" in error_msg or "message can't be edited" in error_msg:
            # Сообщение не найдено, отправляем новое
            logger.warning(f"⚠️ МЕНЮ: Сообщение ID {message_id} не найдено для редактирования")

            try:
                config = await get_valid_config()
                text = format_config_summary(config, user_id)
                keyboard = config_action_keyboard(config.get("ACTIVE", False))

                new_message = await bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=keyboard,
                    disable_web_page_preview=True
                )

                logger.info(f"✅ МЕНЮ: Новое главное меню отправлено (ID {new_message.message_id})")

            except Exception as send_error:
                logger.error(f"❌ МЕНЮ: Ошибка отправки нового главного меню: {send_error}")
        else:
            logger.error(f"❌ МЕНЮ: Неожиданная ошибка обновления главного меню: {e}")

    except Exception as e:
        logger.error(f"💥 МЕНЮ: Критическая ошибка обновления главного меню: {e}")


async def send_main_menu(bot: Bot, chat_id: int, user_id: int) -> int:
    """
    Отправляет главное меню (используется только при первом запуске).

    :param bot: Объект бота
    :param chat_id: ID чата
    :param user_id: ID пользователя
    :return: ID отправленного сообщения
    """
    try:
        config = await get_valid_config()
        text = format_config_summary(config, user_id)
        keyboard = config_action_keyboard(config.get("ACTIVE", False))

        sent = await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )

        logger.info(f"✅ МЕНЮ: Главное меню успешно отправлено (ID {sent.message_id})")
        return sent.message_id

    except Exception as e:
        logger.error(f"❌ МЕНЮ: Ошибка отправки главного меню: {e}")

        # Fallback - отправляем минимальное меню
        try:
            fallback_text = ("⚠️ <b>Ошибка загрузки меню</b>\n\n"
                             "Произошла ошибка при загрузке главного меню.\n"
                             "Попробуйте перезапустить бот командой /start")

            fallback_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Перезапуск", callback_data="main_menu")]
            ])

            sent = await bot.send_message(
                chat_id=chat_id,
                text=fallback_text,
                reply_markup=fallback_keyboard,
                disable_web_page_preview=True
            )

            logger.info(f"✅ МЕНЮ: Минимальное меню отправлено (ID {sent.message_id})")
            return sent.message_id

        except Exception as fallback_error:
            logger.critical(f"💥 МЕНЮ: Критическая ошибка отправки минимального меню: {fallback_error}")
            raise