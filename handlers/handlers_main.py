# handlers/handlers_main.py
"""
Модуль основных хендлеров для главного меню Telegram-бота (система таргетов) - единое сообщение.

Этот модуль содержит функции для:
- Обработки команды /start.
- Переходов по главным кнопкам меню.
- Управления получателем подарков.
- Переключения статуса активности с управлением воркерами.
- ИСПРАВЛЕНО: Правильное использование модуля баланса.

Основные функции:
- command_status_handler: Обрабатывает команду /start.
- start_callback: Переход в главное меню.
- recipient_menu: Управление получателем подарков.
- toggle_active_callback: Переключает статус активности и управляет воркерами.
"""

# --- Сторонние библиотеки ---
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message
from aiogram.fsm.context import FSMContext
import logging

# --- Внутренние модули ---
from services.config import get_valid_config, save_config, format_config_summary, get_target_display_local
from services.menu import update_menu, config_action_keyboard, send_main_menu, safe_edit_menu
from services.balance import refresh_balance  # ИСПРАВЛЕНО: Используем правильный модуль баланса
from services.userbot import is_userbot_active  # ДОБАВЛЕНО: Для проверки активности отправителя
from handlers.wizard_states import ConfigWizard

logger = logging.getLogger(__name__)


def register_main_handlers(dp: Dispatcher, bot: Bot, user_id: int) -> None:
    """
    Регистрирует все основные обработчики событий для главного меню Telegram-бота.
    Включает обработку команд /start, переходов по главным кнопкам,
    управление получателем, переключение статуса с управлением воркерами.
    Все обработчики добавляются в диспетчер dp.
    """

    @dp.message(CommandStart())
    async def command_status_handler(message: Message, state: FSMContext) -> None:
        """
        Обрабатывает команду /start от пользователя.
        Очищает все состояния FSM, обновляет баланс и отправляет главное меню.
        ИСПРАВЛЕНО: Правильное обновление баланса через актуальный модуль.
        """
        # Простая проверка авторизации
        if message.from_user.id != user_id:
            logger.warning(f"🚫 MAIN: Попытка несанкционированного доступа от пользователя {message.from_user.id}")
            await message.answer("⛔️ У вас нет доступа к этому боту.")
            return

        logger.info(f"👤 MAIN: Команда /start от авторизованного пользователя {message.from_user.id}")

        await state.clear()

        # ИСПРАВЛЕНО: Обновляем баланс только если отправитель активен
        if is_userbot_active(user_id):
            logger.info("💰 MAIN: Обновление баланса при запуске")
            try:
                balance = await refresh_balance(user_id)
                logger.info(f"✅ MAIN: Баланс обновлен: {balance:,} ★")
            except Exception as e:
                logger.error(f"❌ MAIN: Ошибка обновления баланса при запуске: {e}")
        else:
            logger.debug("📤 MAIN: Отправитель неактивен - пропускаем обновление баланса")

        # Отправляем главное меню (только при /start)
        await send_main_menu(bot=bot, chat_id=message.chat.id, user_id=message.from_user.id)

    @dp.callback_query(F.data == "main_menu")
    async def start_callback(call: CallbackQuery, state: FSMContext) -> None:
        """
        Обрабатывает нажатие на кнопку "Меню" в интерфейсе бота.
        Очищает все состояния FSM пользователя, обновляет баланс и показывает главное меню в том же сообщении.
        ИСПРАВЛЕНО: Правильное обновление баланса через актуальный модуль.
        """
        # Простая проверка авторизации
        if call.from_user.id != user_id:
            logger.warning(f"🚫 MAIN: Попытка несанкционированного доступа от пользователя {call.from_user.id}")
            await call.answer("⛔️ Нет доступа", show_alert=True)
            return

        await state.clear()
        await call.answer()

        # ИСПРАВЛЕНО: Обновляем баланс только если отправитель активен
        if is_userbot_active(user_id):
            logger.debug("💰 MAIN: Обновление баланса при переходе в главное меню")
            try:
                balance = await refresh_balance(user_id)
                logger.debug(f"✅ MAIN: Баланс обновлен: {balance:,} ★")
            except Exception as e:
                logger.error(f"❌ MAIN: Ошибка обновления баланса: {e}")
        else:
            logger.debug("📤 MAIN: Отправитель неактивен - пропускаем обновление баланса")

        # Обновляем меню в том же сообщении
        await update_menu(
            bot=call.bot,
            chat_id=call.message.chat.id,
            user_id=call.from_user.id,
            message_id=call.message.message_id
        )

        logger.info(f"🏠 MAIN: Успешный переход в главное меню от пользователя {call.from_user.id}")

    @dp.callback_query(F.data == "recipient_menu")
    async def recipient_menu_callback(call: CallbackQuery) -> None:
        """
        Открывает меню управления получателем подарков в том же сообщении.
        Показывает текущего получателя и предлагает его изменить.
        """
        # Простая проверка авторизации
        if call.from_user.id != user_id:
            logger.warning(f"🚫 MAIN: Попытка несанкционированного доступа от пользователя {call.from_user.id}")
            await call.answer("⛔️ Нет доступа", show_alert=True)
            return

        logger.info(f"📥 MAIN: Пользователь {call.from_user.id} перешёл по кнопке \"Получатель\"")

        config = await get_valid_config()
        target_display = get_target_display_local(
            config.get("TARGET_USER_ID"),
            config.get("TARGET_CHAT_ID"),
            call.from_user.id
        )

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Изменить получателя", callback_data="change_recipient")],
            [InlineKeyboardButton(text="☰ Меню", callback_data="main_menu")]
        ])

        text = (f"📥 <b>Управление получателем</b>\n\n"
                f"Текущий получатель: {target_display}\n\n"
                "👉 Нажмите <b>✏️ Изменить</b>, чтобы указать нового получателя подарков.")

        # Редактируем текущее сообщение
        await safe_edit_menu(call.message, text, kb)
        await call.answer()

    @dp.callback_query(F.data == "change_recipient")
    async def change_recipient_callback(call: CallbackQuery, state: FSMContext) -> None:
        """
        Запускает процесс изменения получателя подарков через FSM.
        Отправляет инструкции в том же сообщении.
        """
        # Простая проверка авторизации
        if call.from_user.id != user_id:
            logger.warning(f"🚫 MAIN: Попытка несанкционированного доступа от пользователя {call.from_user.id}")
            await call.answer("⛔️ Нет доступа", show_alert=True)
            return

        logger.info(f"✏️ MAIN: Пользователь {call.from_user.id} перешёл по кнопке \"Изменить получателя\"")

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="☰ Меню", callback_data="main_menu")]
        ])

        message_text = ("📥 <b>Изменение получателя подарков</b>\n\n"
                        "Введите <b>нового получателя</b>:\n\n"
                        f"➤ <b>ID пользователя</b> (например ваш: <code>{call.from_user.id}</code>)\n"
                        "➤ <b>username канала</b> (например: <code>@pepeksey</code>)\n\n"
                        "🔎 <b>Узнать ID пользователя</b> можно тут: @userinfobot\n\n"
                        "⚠️ Чтобы отправить подарок на другой аккаунт, между аккаунтами должна быть переписка.")

        # Редактируем текущее сообщение на инструкции
        await safe_edit_menu(call.message, message_text, kb)
        # Сохраняем ID сообщения для последующего редактирования
        await state.update_data(bot_message_id=call.message.message_id)
        await state.set_state(ConfigWizard.recipient_user_id)
        await call.answer()

    @dp.callback_query(F.data == "toggle_active")
    async def toggle_active_callback(call: CallbackQuery) -> None:
        """
        Переключает статус активности бота для пользователя (активен/неактивен).
        Сохраняет изменения, обновляет интерфейс в том же сообщении и отправляет уведомление о смене статуса.
        Управляет запуском и остановкой фоновых воркеров.
        ИСПРАВЛЕНО: Обновление баланса при активации системы.
        """
        # Простая проверка авторизации
        if call.from_user.id != user_id:
            logger.warning(f"🚫 MAIN: Попытка несанкционированного доступа от пользователя {call.from_user.id}")
            await call.answer("⛔️ Нет доступа", show_alert=True)
            return

        config = await get_valid_config()
        old_status = config.get("ACTIVE", False)
        new_status = not old_status

        config["ACTIVE"] = new_status
        await save_config(config)

        # Импортируем функции управления воркерами
        from main import start_workers, stop_workers, are_workers_running

        if new_status:
            # Включаем систему
            # ДОБАВЛЕНО: Обновляем баланс перед активацией системы
            if is_userbot_active(user_id):
                logger.info("💰 MAIN: Обновление баланса перед активацией системы")
                try:
                    balance = await refresh_balance(user_id)
                    logger.info(f"✅ MAIN: Баланс обновлен перед активацией: {balance:,} ★")
                except Exception as e:
                    logger.error(f"❌ MAIN: Ошибка обновления баланса перед активацией: {e}")

            # Подсчитываем активные подарки для вывода в лог
            targets = config.get("TARGETS", [])
            enabled_targets = [t for t in targets if t.get("ENABLED", True)]
            gifts_count = len(enabled_targets)

            workers_started = await start_workers(bot)

            if workers_started:
                logger.info(f"✅ MAIN: Система успешно активирована, воркеры запущены для {gifts_count} подарков")
                status_message = f"🟢 Система активирована для {gifts_count} подарков"
            else:
                logger.warning("⚠️ MAIN: Система активирована, но воркеры не запущены (не выполнены условия)")
                status_message = "🟡 Система активирована, но проверьте настройки"

                # Возвращаем статус в неактивный если воркеры не запустились
                config["ACTIVE"] = False
                await save_config(config)
                new_status = False
        else:
            # Выключаем систему
            if are_workers_running():
                await stop_workers()
                logger.info("✅ MAIN: Система деактивирована, воркеры остановлены")
                status_message = "🔴 Система деактивирована, воркеры остановлены"
            else:
                logger.info("ℹ️ MAIN: Система деактивирована (воркеры уже были остановлены)")
                status_message = "🔴 Система деактивирована"

        # ИСПРАВЛЕНО: Обновляем конфиг заново для актуального отображения баланса
        config = await get_valid_config()

        # Обновляем главное меню в том же сообщении
        info = format_config_summary(config, call.from_user.id)
        await safe_edit_menu(
            call.message,
            info,
            config_action_keyboard(config["ACTIVE"])
        )

        await call.answer(status_message)