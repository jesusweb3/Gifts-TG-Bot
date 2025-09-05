# handlers/sender_management.py
"""
Модуль хендлеров для управления отправителем (упрощенная версия) - единое сообщение.

Этот модуль содержит функции для:
- Отображения меню управления отправителем.
- Подключения и авторизации отправитель-сессий.
- Управления настройками отправителя (включение/выключение, интервал обновления).
- Удаления отправитель-сессий.

Основные функции:
- sender_menu: Формирует меню управления отправителем.
- on_sender_menu: Обработчик кнопки "Отправитель".
- init_sender_handler: Запуск процесса подключения отправителя.
- sender_enable/disable_handler: Включение/выключение отправителя.
- delete_sender_session: Удаление отправитель-сессии.
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
    is_userbot_active, is_userbot_premium, userbot_send_self, delete_userbot_session,
    start_userbot, continue_userbot_signin, finish_userbot_signin
)
from handlers.wizard_states import ConfigWizard, try_cancel, safe_delete_message
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
            return True
        except Exception as e:
            logger.error(f"Не удалось отредактировать сообщение бота: {e}")

    # Fallback: отправляем новое сообщение
    new_msg = await message.answer(text, reply_markup=reply_markup, disable_web_page_preview=True)
    await state.update_data(bot_message_id=new_msg.message_id)
    return False


@sender_router.callback_query(F.data == "sender_menu")
async def on_sender_menu(call: CallbackQuery):
    """
    Вызывает обновление меню отправителя после колбэка.
    """
    await sender_menu(call.message, call.from_user.id)
    await call.answer()


@sender_router.callback_query(F.data == "sender_menu_edit")
async def on_sender_menu_edit(call: CallbackQuery):
    """
    Вызывает обновление меню отправителя после колбэка (редактирование).
    """
    await sender_menu(call.message, call.from_user.id, True)
    await call.answer()


async def sender_menu(message: Message, user_id: int, edit: bool = False) -> None:
    """
    Формирует и показывает меню управления отправителем для пользователя в едином сообщении.
    """
    config = await get_valid_config()
    sender = config.get("USERBOT", {})

    sender_interval = sender.get("UPDATE_INTERVAL")
    sender_username = sender.get("USERNAME")
    sender_user_id = sender.get("USER_ID")
    sender_first_name = sender.get("FIRST_NAME", "Не указано")
    phone = sender.get("PHONE")
    enabled = sender.get("ENABLED", False)

    if is_userbot_active(user_id):
        is_premium = await is_userbot_premium(user_id)
        status_button = InlineKeyboardButton(
            text="🔕 Выключить" if enabled else "🔔 Включить",
            callback_data="sender_disable" if enabled else "sender_enable"
        )

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
            f"├ <b>Статус:</b> {'🔔 Включён ' if enabled else '🔕 Выключен'}\n"
            f"├ <b>Премиум аккаунт:</b> {'Да' if is_premium else '⚠️ Нет'}\n"
            f"└ <b>Интервал обновления:</b> {sender_interval} секунд\n\n"
            f"❗️ Статус 🔕 <b>приостанавливает</b> работу <b>отправителя</b>."
        )
        keyboard = [
            [
                status_button,
                InlineKeyboardButton(text="🗑 Удалить", callback_data="sender_confirm_delete")
            ],
            [
                InlineKeyboardButton(text="⏳ Интервал", callback_data="sender_interval"),
            ],
            [
                InlineKeyboardButton(text="☰ Меню", callback_data="main_menu")
            ]
        ]
    else:
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


@sender_router.callback_query(F.data == "sender_interval")
async def on_sender_interval(call: CallbackQuery):
    """
    Открывает меню выбора интервала обновления отправителя.
    """
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
        await call.answer("🚫 Неверный интервал.", show_alert=True)
        return

    user_id = call.from_user.id
    config = await get_valid_config()
    config["USERBOT"]["UPDATE_INTERVAL"] = interval
    await save_config(config)

    await call.answer(f"Интервал установлен: {interval} сек")
    await sender_menu(call.message, user_id, edit=True)


@sender_router.callback_query(F.data == "sender_enable")
async def sender_enable_handler(call: CallbackQuery):
    """
    Включает отправитель-сессию в конфигурации и обновляет меню.
    """
    user_id = call.from_user.id
    username = call.from_user.username
    bot_user = await call.bot.get_me()
    bot_username = bot_user.username
    config = await get_valid_config()
    config["USERBOT"]["ENABLED"] = True
    await save_config(config)

    await call.answer("Отправитель включён")

    text_message = (
        f"🔔 <b>Отправитель включён.</b>\n\n"
        f"┌🤖 <b>Бот:</b> @{bot_username}\n"
        f"├👤 <b>Пользователь:</b> @{username} (<code>{user_id}</code>)\n"
        f"└🕒 <b>Время:</b> {now_str()} (UTC)"
    )
    success_send_message = await userbot_send_self(user_id, text_message)

    if success_send_message:
        logger.info("Отправитель успешно включён.")
    else:
        logger.error("Отправитель успешно включён, но сообщение не удалось отправить.")

    await sender_menu(call.message, user_id, edit=True)


@sender_router.callback_query(F.data == "sender_disable")
async def sender_disable_handler(call: CallbackQuery):
    """
    Отключает отправитель-сессию в конфигурации и обновляет меню.
    """
    user_id = call.from_user.id
    username = call.from_user.username
    bot_user = await call.bot.get_me()
    bot_username = bot_user.username
    config = await get_valid_config()
    config["USERBOT"]["ENABLED"] = False
    await save_config(config)

    await call.answer("Отправитель выключен")

    text_message = (
        f"🔕 <b>Отправитель выключен.</b>\n\n"
        f"┌🤖 <b>Бот:</b> @{bot_username}\n"
        f"├👤 <b>Пользователь:</b> @{username} (<code>{user_id}</code>)\n"
        f"└🕒 <b>Время:</b> {now_str()} (UTC)"
    )
    success_send_message = await userbot_send_self(user_id, text_message)

    if success_send_message:
        logger.info("Отправитель успешно выключен.")
    else:
        logger.error("Отправитель успешно выключен, но сообщение не удалось отправить.")

    await sender_menu(call.message, user_id, edit=True)


@sender_router.callback_query(F.data == "sender_confirm_delete")
async def confirm_sender_delete(call: CallbackQuery):
    """
    Запрашивает подтверждение удаления отправитель-сессии у пользователя.
    """
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
    user_id = call.from_user.id
    await call.answer("Отменено.")
    await sender_menu(call.message, user_id, edit=True)


@sender_router.callback_query(F.data == "sender_delete_yes")
async def sender_delete_handler(call: CallbackQuery):
    """
    Удаляет данные отправитель-сессии из конфигурации пользователя.
    """
    user_id = call.from_user.id
    success = await delete_userbot_session(call, user_id)

    if success:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="☰ Меню", callback_data="main_menu")]
        ])

        text = ("✅ <b>Отправитель удалён</b>\n\n"
                "Отправитель успешно удалён.\n"
                "Можете подключить новый аккаунт.")

        await safe_edit_menu(call.message, text, kb)
    else:
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
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="☰ Меню", callback_data="main_menu")]
    ])

    text = ("🔑 <b>Подключение отправителя</b>\n\n"
            "Введите <b>api_id</b>:\n\n"
            "Получить можно на <a href=\"https://my.telegram.org\">my.telegram.org</a>\n\n"
            "/cancel — отмена")

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
    if await try_cancel(message, state):
        return

    if not message.text:
        await safe_delete_message(message)
        return

    text = message.text.strip()

    # Удаляем сообщение пользователя
    await safe_delete_message(message)

    if not text.isdigit() or not (10000 <= int(text) <= 9999999999):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="☰ Меню", callback_data="main_menu")]
        ])

        error_text = ("🚫 <b>Неверный api_id</b>\n\n"
                      "Введите корректное число от 10000 до 9999999999")

        await edit_bot_message(message, state, error_text, kb)
        return

    value = int(text)
    await state.update_data(api_id=value)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="☰ Меню", callback_data="main_menu")]
    ])

    next_text = ("🔑 <b>Подключение отправителя</b>\n\n"
                 "Введите <b>api_hash</b>:\n\n"
                 "32-символьная строка с my.telegram.org\n\n"
                 "/cancel — отмена")

    await edit_bot_message(message, state, next_text, kb)
    await state.set_state(ConfigWizard.userbot_api_hash)


@sender_router.message(ConfigWizard.userbot_api_hash)
async def get_api_hash(message: Message, state: FSMContext):
    """
    Обрабатывает ввод api_hash и переходит к шагу ввода номера телефона.
    """
    if await try_cancel(message, state):
        return

    if not message.text:
        await safe_delete_message(message)
        return

    api_hash = message.text.strip()

    # Удаляем сообщение пользователя
    await safe_delete_message(message)

    if not API_HASH_REGEX.fullmatch(api_hash):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="☰ Меню", callback_data="main_menu")]
        ])

        error_text = ("🚫 <b>Неверный api_hash</b>\n\n"
                      "api_hash должен содержать 32 символа (0-9, a-f)")

        await edit_bot_message(message, state, error_text, kb)
        return

    await state.update_data(api_hash=api_hash)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="☰ Меню", callback_data="main_menu")]
    ])

    next_text = ("📱 <b>Подключение отправителя</b>\n\n"
                 "Введите номер телефона:\n\n"
                 "В формате <code>+490123456789</code>\n\n"
                 "/cancel — отмена")

    await edit_bot_message(message, state, next_text, kb)
    await state.set_state(ConfigWizard.userbot_phone)


@sender_router.message(ConfigWizard.userbot_phone)
async def get_phone(message: Message, state: FSMContext):
    """
    Сохраняет номер телефона и инициирует отправку кода подтверждения.
    """
    if await try_cancel(message, state):
        return

    if not message.text:
        await safe_delete_message(message)
        return

    raw_phone = message.text.strip()
    phone = raw_phone.replace(" ", "")

    # Удаляем сообщение пользователя
    await safe_delete_message(message)

    if not PHONE_REGEX.match(phone):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="☰ Меню", callback_data="main_menu")]
        ])

        error_text = ("🚫 <b>Неверный номер</b>\n\n"
                      "Введите в формате: <code>+490123456789</code>")

        await edit_bot_message(message, state, error_text, kb)
        return

    await state.update_data(phone=phone)

    success = await start_userbot(message, state)
    if not success:
        await sender_menu(message, message.from_user.id, edit=False)
        await state.clear()
        return

    await state.set_state(ConfigWizard.userbot_code)
    await state.update_data(current_code="")

    text = ("📱 <b>Код подтверждения</b>\n\n"
            "Введите полученный код:\n\n"
            "🔢 Код:\n\n"
            "⬅️ — удалить цифру\n🆗 — подтвердить код\n\n"
            "/cancel — отмена")

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
            f"⬅️ — удалить цифру\n🆗 — подтвердить код\n\n"
            f"/cancel — отмена")

    await safe_edit_menu(call.message, text, create_digit_keyboard())


@sender_router.callback_query(F.data == "code_delete", ConfigWizard.userbot_code)
async def on_code_delete(call: CallbackQuery, state: FSMContext):
    """
    Обрабатывает удаление последней цифры из введённого кода подтверждения.
    """
    data = await state.get_data()
    current_code = data.get("current_code", "")[:-1]
    await state.update_data(current_code=current_code)
    await call.answer()

    text = (f"📱 <b>Код подтверждения</b>\n\n"
            f"Введите полученный код:\n\n"
            f"🔢 Код: <b>{current_code}</b>\n\n"
            f"⬅️ — удалить цифру\n🆗 — подтвердить код\n\n"
            f"/cancel — отмена")

    await safe_edit_menu(call.message, text, create_digit_keyboard())


@sender_router.callback_query(F.data == "code_enter", ConfigWizard.userbot_code)
async def on_code_enter(call: CallbackQuery, state: FSMContext):
    """
    Обрабатывает подтверждение кода через инлайн-клавиатуру.
    """
    data = await state.get_data()
    current_code = data.get("current_code", "")

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
                      "⬅️ — удалить цифру\n🆗 — подтвердить код\n\n"
                      "/cancel — отмена")

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
                         "Введите пароль от аккаунта:\n\n"
                         "/cancel — отмена")

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
    if await try_cancel(message, state):
        return

    if not message.text:
        await safe_delete_message(message)
        return

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
    """
    user_id = call.from_user.id
    username = call.from_user.username
    bot_user = await call.bot.get_me()
    bot_username = bot_user.username

    config = await get_valid_config()
    config_id = config["USERBOT"].get("CONFIG_ID")
    from services.config import DEVICE_MODELS, SYSTEM_VERSIONS, APP_VERSIONS
    device_model = DEVICE_MODELS[config_id] if config_id is not None else "Unknown"
    system_version = SYSTEM_VERSIONS[config_id] if config_id is not None else "Unknown"
    app_version = APP_VERSIONS[config_id] if config_id is not None else "Unknown"

    text_success_message = (
        f"✅ <b>Отправитель-сессия успешно авторизована через Telegram-бота.</b>\n\n"
        f"┌🤖 <b>Бот:</b> @{bot_username}\n"
        f"├👤 <b>Пользователь:</b> @{username} (<code>{user_id}</code>)\n"
        f"├📱 <b>Модель устройства:</b> {device_model}\n"
        f"├🖥️ <b>Версия системы:</b> {system_version}\n"
        f"└📱 <b>Версия приложения:</b> {app_version}\n"
    )

    success_send_message = await userbot_send_self(user_id, text_success_message)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Отправитель", callback_data="sender_menu")],
        [InlineKeyboardButton(text="☰ Меню", callback_data="main_menu")]
    ])

    if success_send_message:
        success_text = ("✅ <b>Отправитель подключён!</b>\n\n"
                        "Отправитель успешно подключён и готов к работе.")
    else:
        success_text = ("✅ <b>Отправитель подключён!</b>\n\n"
                        "Отправитель успешно подключён.\n"
                        "🚫 Ошибка при отправке подтверждения.")

    await safe_edit_menu(call.message, success_text, kb)
    await state.clear()


async def sender_success_message_text(message: Message, state: FSMContext):
    """
    Отправляет сообщение об успешном подключении отправителя через Message.
    """
    user_id = message.from_user.id
    username = message.from_user.username
    bot_user = await message.bot.get_me()
    bot_username = bot_user.username

    config = await get_valid_config()
    config_id = config["USERBOT"].get("CONFIG_ID")
    from services.config import DEVICE_MODELS, SYSTEM_VERSIONS, APP_VERSIONS
    device_model = DEVICE_MODELS[config_id] if config_id is not None else "Unknown"
    system_version = SYSTEM_VERSIONS[config_id] if config_id is not None else "Unknown"
    app_version = APP_VERSIONS[config_id] if config_id is not None else "Unknown"

    text_success_message = (
        f"✅ <b>Отправитель-сессия успешно авторизована через Telegram-бота.</b>\n\n"
        f"┌🤖 <b>Бот:</b> @{bot_username}\n"
        f"├👤 <b>Пользователь:</b> @{username} (<code>{user_id}</code>)\n"
        f"├📱 <b>Модель устройства:</b> {device_model}\n"
        f"├🖥️ <b>Версия системы:</b> {system_version}\n"
        f"└📱 <b>Версия приложения:</b> {app_version}\n"
    )

    success_send_message = await userbot_send_self(user_id, text_success_message)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Отправитель", callback_data="sender_menu")],
        [InlineKeyboardButton(text="☰ Меню", callback_data="main_menu")]
    ])

    if success_send_message:
        success_text = ("✅ <b>Отправитель подключён!</b>\n\n"
                        "Отправитель успешно подключён и готов к работе.")
    else:
        success_text = ("✅ <b>Отправитель подключён!</b>\n\n"
                        "Отправитель успешно подключён.\n"
                        "🚫 Ошибка при отправке подтверждения.")

    await edit_bot_message(message, state, success_text, kb)
    await state.clear()


def register_sender_handlers(dp) -> None:
    """
    Регистрирует все хендлеры, связанные с управлением отправителя.
    """
    dp.include_router(sender_router)