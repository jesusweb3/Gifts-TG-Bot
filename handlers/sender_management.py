# handlers/sender_management.py
"""
Модуль хендлеров для управления отправителем (исправленная версия) - единое сообщение.

Этот модуль содержит функции для:
- Отображения меню управления отправителем.
- Подключения и авторизации отправитель-сессий.
- Управления настройками отправителя (интервал обновления).
- Удаления отправитель-сессий (только при неактивной системе).
- ИСПРАВЛЕНО: Автоматическое обновление баланса после авторизации.

Основные функции:
- sender_menu: Формирует меню управления отправителем.
- on_sender_menu: Обработчик кнопки "Отправитель".
- init_sender_handler: Запуск процесса подключения отправителя.
- delete_sender_session: Удаление отправитель-сессии.
- sender_success_message: Успешное подключение с обновлением баланса.
"""

# --- Стандартные библиотеки ---
import logging

# --- Сторонние библиотеки ---
from aiogram import Router, F
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

# --- Внутренние модули ---
from services.config import get_valid_config, save_config
from services.menu import safe_edit_menu
from services.userbot import (
    is_userbot_active, is_userbot_premium, delete_userbot_session,
    start_userbot, continue_userbot_signin, finish_userbot_signin
)
from services.balance import refresh_balance  # ИСПРАВЛЕНО: Используем правильный модуль для баланса
from handlers.wizard_states import ConfigWizard, safe_delete_message
from utils.misc import now_str, PHONE_REGEX, API_HASH_REGEX

logger = logging.getLogger(__name__)
sender_router = Router()


def create_digit_keyboard() -> InlineKeyboardMarkup:
    """Создаёт инлайн-клавиатуру с цифрами для ввода кода."""
    builder = InlineKeyboardBuilder()
    buttons = [
        InlineKeyboardButton(text='1️⃣', callback_data='code_1'),
        InlineKeyboardButton(text='2️⃣', callback_data='code_2'),
        InlineKeyboardButton(text='3️⃣', callback_data='code_3'),
        InlineKeyboardButton(text='4️⃣', callback_data='code_4'),
        InlineKeyboardButton(text='5️⃣', callback_data='code_5'),
        InlineKeyboardButton(text='6️⃣', callback_data='code_6'),
        InlineKeyboardButton(text='7️⃣', callback_data='code_7'),
        InlineKeyboardButton(text='8️⃣', callback_data='code_8'),
        InlineKeyboardButton(text='9️⃣', callback_data='code_9'),
        InlineKeyboardButton(text='⬅️', callback_data='code_delete'),
        InlineKeyboardButton(text='0️⃣', callback_data='code_0'),
        InlineKeyboardButton(text='🆗', callback_data='code_enter')
    ]
    builder.add(*buttons)
    builder.adjust(3)
    return builder.as_markup()


async def edit_bot_message(message: Message, state: FSMContext, text: str,
                           reply_markup: InlineKeyboardMarkup = None) -> bool:
    """
    Редактирует сообщение бота по сохраненному ID или отправляет новое.
    """
    data = await state.get_data()
    bot_message_id = data.get("bot_message_id")

    if bot_message_id:
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=bot_message_id,
                text=text,
                reply_markup=reply_markup,
                disable_web_page_preview=True
            )
            logger.debug(f"✅ ОТПРАВИТЕЛЬ-UI: Сообщение ID {bot_message_id} отредактировано")
            return True
        except Exception as e:
            logger.warning(f"⚠️ ОТПРАВИТЕЛЬ-UI: Не удалось отредактировать сообщение ID {bot_message_id}: {e}")

    # Fallback: отправляем новое сообщение
    new_msg = await message.answer(text, reply_markup=reply_markup, disable_web_page_preview=True)
    await state.update_data(bot_message_id=new_msg.message_id)
    logger.debug(f"📨 ОТПРАВИТЕЛЬ-UI: Отправлено новое сообщение ID {new_msg.message_id}")
    return False


@sender_router.callback_query(F.data == "sender_menu")
async def on_sender_menu(call: CallbackQuery):
    """
    Вызывает обновление меню отправителя после колбэка.
    """
    logger.info(f"📤 SENDER: Пользователь {call.from_user.id} перешёл по кнопке \"Отправитель\"")
    await sender_menu(call.message, call.from_user.id)
    await call.answer()


@sender_router.callback_query(F.data == "sender_menu_edit")
async def on_sender_menu_edit(call: CallbackQuery):
    """
    Вызывает обновление меню отправителя после колбэка (редактирование).
    """
    logger.debug(f"📤 ОТПРАВИТЕЛЬ: Пользователь {call.from_user.id} обновил меню отправителя")
    await sender_menu(call.message, call.from_user.id, True)
    await call.answer()


async def sender_menu(message: Message, user_id: int, edit: bool = False) -> None:
    """
    Формирует и показывает меню управления отправителем для пользователя в едином сообщении.
    ИСПРАВЛЕНО: Правильное отображение баланса.
    """
    logger.debug(f"📤 ОТПРАВИТЕЛЬ: Формирование меню для пользователя {user_id}")

    config = await get_valid_config()
    sender = config.get("USERBOT", {})
    system_active = config.get("ACTIVE", False)

    sender_interval = sender.get("UPDATE_INTERVAL")
    sender_username = sender.get("USERNAME")
    sender_user_id = sender.get("USER_ID")
    sender_first_name = sender.get("FIRST_NAME", "Не указано")
    phone = sender.get("PHONE")

    # ИСПРАВЛЕНО: Получаем баланс из конфига (актуальный)
    sender_balance = sender.get("BALANCE", 0)

    if is_userbot_active(user_id):
        logger.debug(f"✅ ОТПРАВИТЕЛЬ: Отправитель активен для пользователя {user_id}")

        is_premium = await is_userbot_premium(user_id)

        # Показываем имя отправителя
        sender_display = sender_first_name
        if sender_username:
            sender_display += f" (@{sender_username})"

        text = (
            "📤 <b>Управление отправителем</b>\n\n"
            "✅ <b>Отправитель подключён.</b>\n\n"
            f"┌ <b>Отправитель:</b> {sender_display}\n"
            f"├ <b>ID:</b> <code>{sender_user_id}</code>\n"
            f"├ <b>Номер:</b> <code>{phone or '—'}</code>\n"
            f"├ <b>Премиум аккаунт:</b> {'Да' if is_premium else '⚠️ Нет'}\n"
            f"├ <b>Баланс:</b> {sender_balance:,} ★\n"
            f"└ <b>Интервал обновления:</b> {sender_interval} секунд"
        )

        # Кнопки зависят от статуса системы
        if system_active:
            # Система активна - блокируем удаление
            keyboard = [
                [
                    InlineKeyboardButton(text="⏳ Интервал", callback_data="sender_interval"),
                    InlineKeyboardButton(text="🔄 Обновить баланс", callback_data="sender_refresh_balance"),
                ],
                [
                    InlineKeyboardButton(text="🚫 Удаление заблокировано", callback_data="sender_delete_blocked")
                ],
                [
                    InlineKeyboardButton(text="☰ Меню", callback_data="main_menu")
                ]
            ]
            text += "\n\n⚠️ <b>Удаление заблокировано</b> - система активна."
        else:
            # Система неактивна - разрешаем удаление
            keyboard = [
                [
                    InlineKeyboardButton(text="⏳ Интервал", callback_data="sender_interval"),
                    InlineKeyboardButton(text="🔄 Обновить баланс", callback_data="sender_refresh_balance"),
                ],
                [
                    InlineKeyboardButton(text="🗑 Удалить", callback_data="sender_confirm_delete")
                ],
                [
                    InlineKeyboardButton(text="☰ Меню", callback_data="main_menu")
                ]
            ]

        logger.info(
            f"📤 ОТПРАВИТЕЛЬ: Меню сформировано - {sender_display}, баланс: {sender_balance:,} ★, система: {'активна' if system_active else 'неактивна'}")
    else:
        logger.debug(f"❌ ОТПРАВИТЕЛЬ: Отправитель не подключен для пользователя {user_id}")

        text = (
            "📤 <b>Управление отправителем</b>\n\n"
            "🚫 <b>Отправитель не подключён.</b>\n\n"
            "📋 <b>Подготовьте следующие данные:</b>\n\n"
            "🔸 <code>api_id</code>\n"
            "🔸 <code>api_hash</code>\n"
            "🔸 <code>Номер телефона</code>\n\n"
            "📎 Получить <b><a href=\"https://my.telegram.org\">API данные</a></b>\n"
            "📜 Прочитать <b><a href=\"https://core.telegram.org/api/terms\">условия использования</a></b>"
        )
        keyboard = [
            [InlineKeyboardButton(text="➕ Подключить отправитель", callback_data="init_sender")],
            [InlineKeyboardButton(text="☰ Меню", callback_data="main_menu")]
        ]

    markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
    await safe_edit_menu(message, text, markup)


# НОВАЯ ФУНКЦИЯ: Обновление баланса по запросу
@sender_router.callback_query(F.data == "sender_refresh_balance")
async def on_sender_refresh_balance(call: CallbackQuery):
    """
    Обрабатывает запрос на обновление баланса отправителя.
    """
    logger.info(f"🔄 SENDER: Пользователь {call.from_user.id} запросил обновление баланса")

    user_id = call.from_user.id

    # Проверяем что отправитель активен
    if not is_userbot_active(user_id):
        logger.warning(f"⚠️ ОТПРАВИТЕЛЬ: Попытка обновить баланс при неактивном отправителе")
        await call.answer("⚠️ Отправитель неактивен", show_alert=True)
        return

    try:
        # Показываем процесс обновления
        await call.answer("🔄 Обновление баланса...")

        # Обновляем баланс через правильный модуль
        new_balance = await refresh_balance(user_id)

        # Обновляем меню с новым балансом
        await sender_menu(call.message, user_id, edit=True)

        logger.info(f"✅ ОТПРАВИТЕЛЬ: Баланс обновлен для пользователя {user_id}: {new_balance:,} ★")

    except Exception as e:
        logger.error(f"❌ ОТПРАВИТЕЛЬ: Ошибка обновления баланса: {e}")
        await call.answer("❌ Ошибка обновления баланса", show_alert=True)


@sender_router.callback_query(F.data == "sender_delete_blocked")
async def on_sender_delete_blocked(call: CallbackQuery):
    """
    Обрабатывает нажатие на заблокированную кнопку удаления.
    """
    logger.info(f"🚫 SENDER: Пользователь {call.from_user.id} попытался удалить отправитель при активной системе")
    await call.answer("🚫 Отключите систему перед удалением отправителя!", show_alert=True)


@sender_router.callback_query(F.data == "sender_interval")
async def on_sender_interval(call: CallbackQuery):
    """
    Открывает меню выбора интервала обновления отправителя.
    """
    logger.info(f"⏳ SENDER: Пользователь {call.from_user.id} перешёл по кнопке \"Интервал\"")

    config = await get_valid_config()
    current_interval = config.get("USERBOT", {}).get("UPDATE_INTERVAL", 45)

    logger.debug(f"⏳ ОТПРАВИТЕЛЬ: Текущий интервал: {current_interval} секунд")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="30 секунд", callback_data="edit_sender_interval_30"),
            InlineKeyboardButton(text="45 секунд", callback_data="edit_sender_interval_45")
        ],
        [
            InlineKeyboardButton(text="60 секунд", callback_data="edit_sender_interval_60"),
            InlineKeyboardButton(text="90 секунд", callback_data="edit_sender_interval_90")
        ],
        [
            InlineKeyboardButton(text="📤 Отправитель", callback_data="sender_menu_edit"),
            InlineKeyboardButton(text="☰ Меню", callback_data="main_menu")
        ]
    ])

    text = ("⏳ <b>Интервал обновления</b>\n\n"
            "Выберите интервал обновления списка подарков через отправитель:\n\n"
            "❗️ Рекомендуется использовать <b>45 секунд</b>.\n"
            "⚠️ Частые запросы могут привести к <b>блокировке или ограничению со стороны Telegram</b>.")

    await safe_edit_menu(call.message, text, kb)
    await call.answer()


@sender_router.callback_query(lambda c: c.data.startswith("edit_sender_interval_"))
async def edit_sender_interval(call: CallbackQuery):
    """
    Обрабатывает изменение интервала обновления отправителя.
    """
    interval_mapping = {
        "edit_sender_interval_30": 30,
        "edit_sender_interval_45": 45,
        "edit_sender_interval_60": 60,
        "edit_sender_interval_90": 90
    }

    interval = interval_mapping.get(call.data)
    if interval is None:
        logger.error(f"❌ ОТПРАВИТЕЛЬ: Неверный callback для интервала: {call.data}")
        await call.answer("🚫 Неверный интервал.", show_alert=True)
        return

    logger.info(f"⏳ SENDER: Пользователь {call.from_user.id} установил интервал {interval} секунд")

    user_id = call.from_user.id
    config = await get_valid_config()
    config["USERBOT"]["UPDATE_INTERVAL"] = interval
    await save_config(config)

    await call.answer(f"Интервал установлен: {interval} сек")
    await sender_menu(call.message, user_id, edit=True)


@sender_router.callback_query(F.data == "sender_confirm_delete")
async def confirm_sender_delete(call: CallbackQuery):
    """
    Запрашивает подтверждение удаления отправитель-сессии у пользователя.
    Проверяет что система неактивна.
    """
    logger.info(f"🗑️ SENDER: Пользователь {call.from_user.id} перешёл по кнопке \"Удалить\"")

    # Дополнительная проверка статуса системы
    config = await get_valid_config()
    if config.get("ACTIVE", False):
        logger.warning(f"🚫 ОТПРАВИТЕЛЬ: Попытка удаления при активной системе от пользователя {call.from_user.id}")
        await call.answer("🚫 Отключите систему перед удалением отправителя!", show_alert=True)
        return

    sender = config.get("USERBOT", {})
    sender_name = sender.get("FIRST_NAME", "Неизвестно")
    sender_phone = sender.get("PHONE", "Не указан")

    logger.debug(f"🗑️ ОТПРАВИТЕЛЬ: Подтверждение удаления - {sender_name} ({sender_phone})")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да", callback_data="sender_delete_yes"),
            InlineKeyboardButton(text="❌ Нет", callback_data="sender_delete_no")
        ]
    ])

    text = ("⚠️ <b>Удаление отправителя</b>\n\n"
            "Вы уверены, что хотите <b>удалить отправитель</b>?\n\n"
            "Все данные авторизации будут удалены.")

    await safe_edit_menu(call.message, text, kb)
    await call.answer()


@sender_router.callback_query(F.data == "sender_delete_no")
async def cancel_sender_delete(call: CallbackQuery):
    """
    Отменяет процесс удаления отправитель-сессии и возвращает в меню.
    """
    logger.info(f"↩️ SENDER: Пользователь {call.from_user.id} перешёл по кнопке \"Нет\"")

    user_id = call.from_user.id
    await call.answer("Отменено.")
    await sender_menu(call.message, user_id, edit=True)


@sender_router.callback_query(F.data == "sender_delete_yes")
async def sender_delete_handler(call: CallbackQuery):
    """
    Удаляет данные отправитель-сессии из конфигурации пользователя.
    Проверяет что система неактивна.
    """
    user_id = call.from_user.id

    logger.info(f"🗑️ SENDER: Пользователь {call.from_user.id} перешёл по кнопке \"Да\"")

    # Финальная проверка статуса системы
    config = await get_valid_config()
    if config.get("ACTIVE", False):
        logger.warning(f"🚫 ОТПРАВИТЕЛЬ: Финальная блокировка удаления при активной системе от пользователя {user_id}")
        await call.answer("🚫 Отключите систему перед удалением отправителя!", show_alert=True)
        # Возвращаемся в меню отправителя
        await sender_menu(call.message, user_id, edit=True)
        return

    sender = config.get("USERBOT", {})
    sender_name = sender.get("FIRST_NAME", "Неизвестно")

    success = await delete_userbot_session(call, user_id)

    if success:
        logger.info(f"✅ ОТПРАВИТЕЛЬ: Отправитель '{sender_name}' успешно удален")

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="☰ Меню", callback_data="main_menu")]
        ])

        text = ("✅ <b>Отправитель удалён</b>\n\n"
                "Отправитель успешно удалён.\n"
                "Можете подключить новый аккаунт.")

        await safe_edit_menu(call.message, text, kb)
    else:
        logger.error(f"❌ ОТПРАВИТЕЛЬ: Не удалось удалить отправитель '{sender_name}'")

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="☰ Меню", callback_data="main_menu")]
        ])

        text = ("🚫 <b>Ошибка удаления</b>\n\n"
                "Не удалось удалить отправитель.\n"
                "Возможно, он уже был удалён.")

        await safe_edit_menu(call.message, text, kb)

    await call.answer()


# === Процесс подключения отправителя ===

@sender_router.callback_query(F.data == "init_sender")
async def init_sender_handler(call: CallbackQuery, state: FSMContext):
    """
    Запускает процесс подключения новой отправитель-сессии (шаг ввода api_id).
    """
    logger.info(f"🔐 SENDER: Пользователь {call.from_user.id} перешёл по кнопке \"Подключить отправитель\"")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="☰ Меню", callback_data="main_menu")]
    ])

    text = ("🔑 <b>Подключение отправителя</b>\n\n"
            "Введите <b>api_id</b>:\n\n"
            "Получить можно на <a href=\"https://my.telegram.org\">my.telegram.org</a>")

    await safe_edit_menu(call.message, text, kb)
    # Сохраняем ID сообщения для последующего редактирования
    await state.update_data(bot_message_id=call.message.message_id)
    await state.set_state(ConfigWizard.userbot_api_id)
    await call.answer()


@sender_router.message(ConfigWizard.userbot_api_id)
async def get_api_id(message: Message, state: FSMContext):
    """
    Обрабатывает ввод api_id от пользователя и переходит к следующему шагу.
    """
    if not message.text:
        await safe_delete_message(message)
        return

    api_id_input = message.text.strip()

    # Удаляем сообщение пользователя
    await safe_delete_message(message)

    if not api_id_input.isdigit() or not (10000 <= int(api_id_input) <= 9999999999):
        logger.warning(f"❌ ОТПРАВИТЕЛЬ-МАСТЕР: Невалидный API_ID: {api_id_input}")

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="☰ Меню", callback_data="main_menu")]
        ])

        error_text = ("🚫 <b>Неверный api_id</b>\n\n"
                      "Введите корректное число от 10000 до 9999999999")

        await edit_bot_message(message, state, error_text, kb)
        return

    value = int(api_id_input)
    await state.update_data(api_id=value)

    logger.info(f"🔑 ОТПРАВИТЕЛЬ-МАСТЕР: Пользователь {message.from_user.id} ввел валидный API_ID: {value}")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="☰ Меню", callback_data="main_menu")]
    ])

    next_text = ("🔑 <b>Подключение отправителя</b>\n\n"
                 "Введите <b>api_hash</b>:\n\n"
                 "32-символьная строка с my.telegram.org")

    await edit_bot_message(message, state, next_text, kb)
    await state.set_state(ConfigWizard.userbot_api_hash)


@sender_router.message(ConfigWizard.userbot_api_hash)
async def get_api_hash(message: Message, state: FSMContext):
    """
    Обрабатывает ввод api_hash и переходит к шагу ввода номера телефона.
    """
    if not message.text:
        await safe_delete_message(message)
        return

    api_hash = message.text.strip()

    # Удаляем сообщение пользователя
    await safe_delete_message(message)

    if not API_HASH_REGEX.fullmatch(api_hash):
        logger.warning(f"❌ ОТПРАВИТЕЛЬ-МАСТЕР: Невалидный API_HASH: {api_hash[:8]}...")

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="☰ Меню", callback_data="main_menu")]
        ])

        error_text = ("🚫 <b>Неверный api_hash</b>\n\n"
                      "api_hash должен содержать 32 символа (0-9, a-f)")

        await edit_bot_message(message, state, error_text, kb)
        return

    await state.update_data(api_hash=api_hash)

    logger.info(f"🔑 ОТПРАВИТЕЛЬ-МАСТЕР: Пользователь {message.from_user.id} ввел валидный API_HASH: {api_hash[:8]}...")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="☰ Меню", callback_data="main_menu")]
    ])

    next_text = ("📱 <b>Подключение отправителя</b>\n\n"
                 "Введите номер телефона:\n\n"
                 "В формате <code>+490123456789</code>")

    await edit_bot_message(message, state, next_text, kb)
    await state.set_state(ConfigWizard.userbot_phone)


@sender_router.message(ConfigWizard.userbot_phone)
async def get_phone(message: Message, state: FSMContext):
    """
    Сохраняет номер телефона и инициирует отправку кода подтверждения.
    """
    if not message.text:
        await safe_delete_message(message)
        return

    raw_phone = message.text.strip()
    phone = raw_phone.replace(" ", "")

    # Удаляем сообщение пользователя
    await safe_delete_message(message)

    if not PHONE_REGEX.match(phone):
        logger.warning(f"❌ ОТПРАВИТЕЛЬ-МАСТЕР: Невалидный номер телефона: {phone}")

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="☰ Меню", callback_data="main_menu")]
        ])

        error_text = ("🚫 <b>Неверный номер</b>\n\n"
                      "Введите в формате: <code>+490123456789</code>")

        await edit_bot_message(message, state, error_text, kb)
        return

    await state.update_data(phone=phone)

    logger.info(f"📱 ОТПРАВИТЕЛЬ-МАСТЕР: Пользователь {message.from_user.id} ввел валидный телефон: {phone}")

    success = await start_userbot(message, state)
    if not success:
        logger.error("❌ ОТПРАВИТЕЛЬ-МАСТЕР: Не удалось отправить код подтверждения")
        await sender_menu(message, message.from_user.id, edit=False)
        await state.clear()
        return

    await state.set_state(ConfigWizard.userbot_code)
    await state.update_data(current_code="")

    text = ("📱 <b>Код подтверждения</b>\n\n"
            "Введите полученный код:\n\n"
            "🔢 Код:\n\n"
            "⬅️ — удалить цифру\n🆗 — подтвердить код")

    await edit_bot_message(message, state, text, create_digit_keyboard())


@sender_router.callback_query(F.data.regexp(r"^code_\d$"), ConfigWizard.userbot_code)
async def on_code_digit(call: CallbackQuery, state: FSMContext):
    """
    Обрабатывает добавление цифры в код подтверждения через инлайн-клавиатуру.
    """
    digit = call.data.split('_')[1]
    data = await state.get_data()
    current_code = data.get("current_code", "") + digit
    await state.update_data(current_code=current_code)

    await call.answer()

    text = (f"📱 <b>Код подтверждения</b>\n\n"
            f"Введите полученный код:\n\n"
            f"🔢 Код: <b>{current_code}</b>\n\n"
            f"⬅️ — удалить цифру\n🆗 — подтвердить код")

    await safe_edit_menu(call.message, text, create_digit_keyboard())


@sender_router.callback_query(F.data == "code_delete", ConfigWizard.userbot_code)
async def on_code_delete(call: CallbackQuery, state: FSMContext):
    """
    Обрабатывает удаление последней цифры из введённого кода подтверждения.
    """
    data = await state.get_data()
    old_code = data.get("current_code", "")
    current_code = old_code[:-1]
    await state.update_data(current_code=current_code)

    await call.answer()

    text = (f"📱 <b>Код подтверждения</b>\n\n"
            f"Введите полученный код:\n\n"
            f"🔢 Код: <b>{current_code}</b>\n\n"
            f"⬅️ — удалить цифру\n🆗 — подтвердить код")

    await safe_edit_menu(call.message, text, create_digit_keyboard())


@sender_router.callback_query(F.data == "code_enter", ConfigWizard.userbot_code)
async def on_code_enter(call: CallbackQuery, state: FSMContext):
    """
    Обрабатывает подтверждение кода через инлайн-клавиатуру.
    """
    data = await state.get_data()
    current_code = data.get("current_code", "")

    logger.info(f"🔐 ОТПРАВИТЕЛЬ-МАСТЕР: Пользователь {call.from_user.id} отправляет код: {current_code}")

    if not (4 <= len(current_code) <= 6):
        await call.answer("🚫 Код должен быть от 4 до 6 символов. Попробуйте ещё раз.", show_alert=True)
        return

    processing_text = (f"🔄 <b>Проверка кода...</b>\n\n"
                       f"Код: <b>{current_code}</b>\n\n"
                       f"Проверяем код подтверждения...")

    await safe_edit_menu(call.message, processing_text, None)

    await state.update_data(code=current_code)

    success, need_password, retry = await continue_userbot_signin(call, state)

    if retry:
        await state.set_state(ConfigWizard.userbot_code)
        await state.update_data(current_code="")

        retry_text = ("📱 <b>Код подтверждения</b>\n\n"
                      "Неверный код. Попробуйте ещё раз:\n\n"
                      "🔢 Код:\n\n"
                      "⬅️ — удалить цифру\n🆗 — подтвердить код")

        await safe_edit_menu(call.message, retry_text, create_digit_keyboard())
        return

    if not success:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="☰ Меню", callback_data="main_menu")]
        ])

        error_text = ("🚫 <b>Ошибка авторизации</b>\n\n"
                      "Не удалось авторизоваться с введённым кодом.")

        await safe_edit_menu(call.message, error_text, kb)
        await state.clear()
        await call.answer()
        return

    if need_password:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="☰ Меню", callback_data="main_menu")]
        ])

        password_text = ("🔐 <b>Облачный пароль</b>\n\n"
                         "Введите пароль от аккаунта:")

        await safe_edit_menu(call.message, password_text, kb)
        await state.set_state(ConfigWizard.userbot_password)
    else:
        await sender_success_message(call, state)

    await call.answer()


@sender_router.message(ConfigWizard.userbot_password)
async def get_password(message: Message, state: FSMContext):
    """
    Обрабатывает ввод пароля от Telegram-аккаунта и завершает авторизацию отправителя.
    """
    if not message.text:
        await safe_delete_message(message)
        return

    logger.info(f"🔐 ОТПРАВИТЕЛЬ-МАСТЕР: Пользователь {message.from_user.id} ввел облачный пароль")

    # Удаляем сообщение пользователя с паролем
    await safe_delete_message(message)

    await state.update_data(password=message.text.strip())

    success, retry = await finish_userbot_signin(message, state)

    if retry:
        return

    if success:
        await sender_success_message_text(message, state)
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="☰ Меню", callback_data="main_menu")]
        ])

        error_text = ("🚫 <b>Неверный пароль</b>\n\n"
                      "Подключение отправителя прервано.")

        await edit_bot_message(message, state, error_text, kb)

    await state.clear()


async def sender_success_message(call: CallbackQuery, state: FSMContext):
    """
    Отправляет сообщение об успешном подключении отправителя через CallbackQuery.
    ИСПРАВЛЕНО: Автоматически обновляет баланс после успешной авторизации.
    """
    user_id = call.from_user.id

    # КРИТИЧНО: Обновляем баланс сразу после успешной авторизации
    logger.info(f"🔄 ОТПРАВИТЕЛЬ: Обновление баланса после успешной авторизации для пользователя {user_id}")
    try:
        new_balance = await refresh_balance(user_id)
        logger.info(f"✅ ОТПРАВИТЕЛЬ: Баланс обновлен после авторизации: {new_balance:,} ★")
    except Exception as balance_error:
        logger.error(f"❌ ОТПРАВИТЕЛЬ: Не удалось обновить баланс после авторизации: {balance_error}")
        new_balance = 0

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Отправитель", callback_data="sender_menu")],
        [InlineKeyboardButton(text="☰ Меню", callback_data="main_menu")]
    ])

    success_text = (f"✅ <b>Отправитель подключён!</b>\n\n"
                    f"Отправитель успешно подключён и готов к работе.\n"
                    f"💰 Баланс: {new_balance:,} ★")

    await safe_edit_menu(call.message, success_text, kb)
    await state.clear()


async def sender_success_message_text(message: Message, state: FSMContext):
    """
    Отправляет сообщение об успешном подключении отправителя через Message.
    ИСПРАВЛЕНО: Автоматически обновляет баланс после успешной авторизации.
    """
    user_id = message.from_user.id

    # КРИТИЧНО: Обновляем баланс сразу после успешной авторизации
    logger.info(f"🔄 ОТПРАВИТЕЛЬ: Обновление баланса после успешной авторизации для пользователя {user_id}")
    try:
        new_balance = await refresh_balance(user_id)
        logger.info(f"✅ ОТПРАВИТЕЛЬ: Баланс обновлен после авторизации: {new_balance:,} ★")
    except Exception as balance_error:
        logger.error(f"❌ ОТПРАВИТЕЛЬ: Не удалось обновить баланс после авторизации: {balance_error}")
        new_balance = 0

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Отправитель", callback_data="sender_menu")],
        [InlineKeyboardButton(text="☰ Меню", callback_data="main_menu")]
    ])

    success_text = (f"✅ <b>Отправитель подключён!</b>\n\n"
                    f"Отправитель успешно подключён и готов к работе.\n"
                    f"💰 Баланс: {new_balance:,} ★")

    await edit_bot_message(message, state, success_text, kb)
    await state.clear()


def register_sender_handlers(dp) -> None:
    """
    Регистрирует все хендлеры, связанные с управлением отправителя.
    """
    dp.include_router(sender_router)
    logger.debug("📝 ОТПРАВИТЕЛЬ: Обработчики отправителя зарегистрированы")