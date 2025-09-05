# handlers/sender_management.py
"""
Модуль хендлеров для управления отправителем (упрощенная версия).

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
from services.menu import update_menu
from services.balance import refresh_balance
from services.userbot import (
    is_userbot_active, is_userbot_premium, userbot_send_self, delete_userbot_session,
    start_userbot, continue_userbot_signin, finish_userbot_signin
)
from handlers.wizard_states import ConfigWizard, try_cancel, safe_edit_text
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
    Формирует и отправляет (или редактирует) меню управления отправителем для пользователя.
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
                InlineKeyboardButton(text="☰ Меню", callback_data="sender_main_menu")
            ]
        ]
    else:
        text = (
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
            [InlineKeyboardButton(text="☰ Меню", callback_data="sender_main_menu")]
        ]

    markup = InlineKeyboardMarkup(inline_keyboard=keyboard)

    try:
        if edit:
            await message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
        else:
            await message.answer(text, reply_markup=markup, disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"⚠️ Ошибка при обновлении меню: {e}")


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
            InlineKeyboardButton(text="☰ Меню", callback_data="sender_main_menu")
        ]
    ])
    await call.message.edit_text(
        "⏳ Выберите интервал обновления списка подарков через отправитель:\n\n"
        "❗️ Рекомендуется использовать <b>45 секунд</b>.\n"
        "⚠️ Частые запросы могут привести к <b>блокировке или ограничению со стороны Telegram</b>.",
        reply_markup=kb
    )
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

    await call.answer()
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

    await call.answer()

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

    await call.answer()

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
    await call.message.edit_text(
        "❗ Вы уверены, что хотите <b>удалить отправитель</b>?",
        reply_markup=kb
    )
    await call.answer()


@sender_router.callback_query(F.data == "sender_delete_no")
async def cancel_sender_delete(call: CallbackQuery):
    """
    Отменяет процесс удаления отправитель-сессии и возвращает в меню.
    """
    user_id = call.from_user.id
    await call.answer("Отменено.", show_alert=True)
    await sender_menu(call.message, user_id, edit=True)


@sender_router.callback_query(F.data == "sender_delete_yes")
async def sender_delete_handler(call: CallbackQuery):
    """
    Удаляет данные отправитель-сессии из конфигурации пользователя.
    """
    user_id = call.from_user.id
    success = await delete_userbot_session(call, user_id)

    if success:
        await call.message.answer("✅ Отправитель удалён.")
        await sender_menu(call.message, user_id, edit=False)
    else:
        await call.message.answer("🚫 Не удалось удалить отправитель. Возможно, он уже был удалён.")
        await sender_menu(call.message, user_id, edit=False)

    await call.answer()


@sender_router.callback_query(F.data == "sender_main_menu")
async def sender_main_menu_callback(call: CallbackQuery, state: FSMContext):
    """
    Показывает главное меню по нажатию кнопки "Меню".
    Очищает все состояния FSM для пользователя.
    """
    await state.clear()
    await call.answer()
    await safe_edit_text(call.message, "✅ Настройка отправителя завершена.", reply_markup=None)
    await refresh_balance()
    await update_menu(
        bot=call.bot,
        chat_id=call.message.chat.id,
        user_id=call.from_user.id,
        message_id=call.message.message_id
    )


# === Процесс подключения отправителя ===

@sender_router.callback_query(F.data == "init_sender")
async def init_sender_handler(call: CallbackQuery, state: FSMContext):
    """
    Запускает процесс подключения новой отправитель-сессии (шаг ввода api_id).
    """
    await call.message.answer("📥 Введите <b>api_id</b>:\n\n/cancel — отмена")
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
        await message.answer("🚫 Поддерживается только текстовый ввод данных.\n\n/cancel — отмена")
        return

    text = message.text.strip()

    if not text.isdigit() or not (10000 <= int(text) <= 9999999999):
        await message.answer("🚫 Неверный формат. Введите корректное число.\n\n/cancel — отмена")
        return

    value = int(text)
    await state.update_data(api_id=value)
    await message.answer("📥 Введите <b>api_hash</b>:\n\n/cancel — отмена")
    await state.set_state(ConfigWizard.userbot_api_hash)


@sender_router.message(ConfigWizard.userbot_api_hash)
async def get_api_hash(message: Message, state: FSMContext):
    """
    Обрабатывает ввод api_hash и переходит к шагу ввода номера телефона.
    """
    if await try_cancel(message, state):
        return

    if not message.text:
        await message.answer("🚫 Поддерживается только текстовый ввод данных.\n\n/cancel — отмена")
        return

    api_hash = message.text.strip()

    if not API_HASH_REGEX.fullmatch(api_hash):
        await message.answer(
            "🚫 Неверный формат. Убедитесь, что api_hash скопирован полностью (32 символа).\n\n/cancel — отмена")
        return

    await state.update_data(api_hash=api_hash)
    await message.answer("📥 Введите номер телефона (в формате <code>+490123456789</code>):\n\n/cancel — отмена")
    await state.set_state(ConfigWizard.userbot_phone)


@sender_router.message(ConfigWizard.userbot_phone)
async def get_phone(message: Message, state: FSMContext):
    """
    Сохраняет номер телефона и инициирует отправку кода подтверждения.
    """
    if await try_cancel(message, state):
        return

    if not message.text:
        await message.answer("🚫 Поддерживается только текстовый ввод данных.\n\n/cancel — отмена")
        return

    raw_phone = message.text.strip()
    phone = raw_phone.replace(" ", "")

    if not PHONE_REGEX.match(phone):
        await message.answer(
            "🚫 Неверный формат номера телефона.\nВведите в формате: <code>+490123456789</code>\n\n/cancel — отмена")
        return

    await state.update_data(phone=phone)

    success = await start_userbot(message, state)
    if not success:
        await sender_menu(message, message.from_user.id, edit=False)
        await state.clear()
        return
    await state.set_state(ConfigWizard.userbot_code)
    await state.update_data(current_code="")
    await message.answer(
        text=f"📥 Введите полученный код:\n\n🔢 Код:\n\n⬅️ — удалить цифру\n🆗 — подтвердить код\n\n/cancel — отмена",
        reply_markup=create_digit_keyboard())


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
    await call.bot.edit_message_text(
        f"📥 Введите полученный код:\n\n🔢 Код: <b>{current_code}</b>\n\n⬅️ — удалить цифру\n🆗 — подтвердить код\n\n/cancel — отмена",
        chat_id=call.from_user.id,
        message_id=call.message.message_id,
        reply_markup=create_digit_keyboard()
    )


@sender_router.callback_query(F.data == "code_delete", ConfigWizard.userbot_code)
async def on_code_delete(call: CallbackQuery, state: FSMContext):
    """
    Обрабатывает удаление последней цифры из введённого кода подтверждения.
    """
    data = await state.get_data()
    current_code = data.get("current_code", "")[:-1]
    await state.update_data(current_code=current_code)
    await call.answer()
    await call.bot.edit_message_text(
        f"📥 Введите полученный код:\n\n🔢 Код: <b>{current_code}</b>\n\n⬅️ — удалить цифру\n🆗 — подтвердить код\n\n/cancel — отмена",
        chat_id=call.from_user.id,
        message_id=call.message.message_id,
        reply_markup=create_digit_keyboard()
    )


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

    await call.bot.edit_message_text(
        f"🔢 Введённый код: <b>{current_code}</b>",
        chat_id=call.from_user.id,
        message_id=call.message.message_id
    )

    await state.update_data(code=current_code)
    success, need_password, retry = await continue_userbot_signin(call, state)
    if retry:
        await state.set_state(ConfigWizard.userbot_code)
        await state.update_data(current_code="")
        await call.message.answer(
            text=f"📥 Введите полученный код:\n\n🔢 Код:\n\n⬅️ — удалить цифру\n🆗 — подтвердить код\n\n/cancel — отмена",
            reply_markup=create_digit_keyboard())
        return
    if not success:
        await call.message.answer("🚫 Ошибка кода. Подключение отправителя прервано.")
        await sender_menu(call.message, call.from_user.id, edit=False)
        await state.clear()
        await call.answer()
        return
    if need_password:
        await call.message.answer("📥 Введите пароль:\n\n/cancel — отмена")
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
        await message.answer("🚫 Поддерживается только текстовый ввод данных.\n\n/cancel — отмена")
        return

    await state.update_data(password=message.text.strip())
    success, retry = await finish_userbot_signin(message, state)
    if retry:
        return
    if success:
        await sender_success_message_text(message, state)
    else:
        await message.answer("🚫 Неверный пароль. Подключение отправителя прервано.")

    await sender_menu(message, message.from_user.id, edit=False)
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

    if success_send_message:
        await call.message.answer("✅ Отправитель успешно подключён.")
    else:
        await call.message.answer("✅ Отправитель успешно подключён.\n🚫 Ошибка при отправке подтверждения.")

    await sender_menu(call.message, call.from_user.id, edit=False)
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

    if success_send_message:
        await message.answer("✅ Отправитель успешно подключён.")
    else:
        await message.answer("✅ Отправитель успешно подключён.\n🚫 Ошибка при отправке подтверждения.")

    await state.clear()


def register_sender_handlers(dp) -> None:
    """
    Регистрирует все хендлеры, связанные с управлением отправителя.
    """
    dp.include_router(sender_router)