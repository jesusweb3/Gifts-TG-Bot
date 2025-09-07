# handlers/wizard_states.py
"""
Модуль FSM состояний и общих утилит для wizard handlers (система таргетов) - единое сообщение.

Этот модуль содержит:
- Определения всех FSM состояний для пошагового редактирования.
- Общие утилиты для редактирования сообщений.
- Обработчики пошаговых состояний создания и редактирования таргетов.
- Обработчики для изменения получателя подарков.
- Удаление пользовательских сообщений для чистоты чата.

Основные классы и функции:
- ConfigWizard: Класс состояний FSM для пошагового редактирования.
- safe_edit_text: Безопасное редактирование сообщений.
- safe_delete_message: Безопасное удаление пользовательских сообщений.
"""

# --- Стандартные библиотеки ---
import logging

# --- Сторонние библиотеки ---
from aiogram import Router, Bot
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest

# --- Внутренние модули ---
from services.config import get_valid_config, save_config, add_target, update_target
from services.gifts_userbot import validate_gift_id, check_gift_availability

logger = logging.getLogger(__name__)
wizard_states_router = Router()


class ConfigWizard(StatesGroup):
    """
    Класс состояний для FSM wizard (пошаговое редактирование конфигурации).
    Каждый state — отдельный шаг процесса.
    """
    # Создание таргета
    target_gift_id = State()
    target_max_price = State()

    # Редактирование таргета
    edit_target_price = State()

    # Изменение получателя
    recipient_user_id = State()

    # Отправитель авторизация
    userbot_api_id = State()
    userbot_api_hash = State()
    userbot_phone = State()
    userbot_code = State()
    userbot_password = State()


async def safe_delete_message(message: Message) -> None:
    """
    Безопасно удаляет сообщение пользователя, игнорируя ошибки.
    """
    try:
        await message.delete()
        logger.debug(f"🗑️ СООБЩЕНИЯ: Удалено сообщение пользователя ID {message.message_id}")
    except Exception as e:
        logger.debug(f"🗑️ СООБЩЕНИЯ: Не удалось удалить сообщение ID {message.message_id}: {e}")


async def safe_edit_text(message: Message, text: str, reply_markup: InlineKeyboardMarkup = None) -> bool:
    """
    Безопасно редактирует текст сообщения, игнорируя ошибки "нельзя редактировать" и "сообщение не найдено".
    """
    try:
        await message.edit_text(text, reply_markup=reply_markup, disable_web_page_preview=True)
        logger.debug(f"✅ СООБЩЕНИЯ: Сообщение ID {message.message_id} успешно отредактировано")
        return True
    except TelegramBadRequest as e:
        logger.debug(f"⚠️ СООБЩЕНИЯ: Ошибка редактирования сообщения ID {message.message_id}: {e}")
        if "message can't be edited" in str(e) or "message to edit not found" in str(e):
            return False
        else:
            raise


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
            logger.debug(f"✅ СООБЩЕНИЯ: Сообщение бота ID {bot_message_id} успешно отредактировано")
            return True
        except Exception as e:
            logger.warning(f"⚠️ СООБЩЕНИЯ: Не удалось отредактировать сообщение бота ID {bot_message_id}: {e}")

    # Fallback: отправляем новое сообщение
    new_msg = await message.answer(text, reply_markup=reply_markup, disable_web_page_preview=True)
    await state.update_data(bot_message_id=new_msg.message_id)
    logger.debug(f"📨 СООБЩЕНИЯ: Отправлено новое сообщение бота ID {new_msg.message_id}")
    return False


async def simple_get_chat_type(bot: Bot, username: str) -> str:
    """
    Упрощенная функция определения типа чата по username.
    """
    if not username.startswith("@"):
        username = "@" + username

    logger.debug(f"🔍 ПРОВЕРКА: Определение типа чата для {username}")

    try:
        chat = await bot.get_chat(username)
        if chat.type == "private":
            chat_type = "user" if not getattr(chat, "is_bot", False) else "bot"
        elif chat.type == "channel":
            chat_type = "channel"
        else:
            chat_type = "group"

        logger.debug(f"✅ ПРОВЕРКА: Тип чата {username}: {chat_type}")
        return chat_type
    except Exception as e:
        logger.debug(f"⚠️ ПРОВЕРКА: Не удалось определить тип чата {username}: {e}")
        return "unknown"


# === Обработчики создания таргета ===

@wizard_states_router.message(ConfigWizard.target_gift_id)
async def step_target_gift_id(message: Message, state: FSMContext):
    """
    Обработка ввода ID подарка для нового таргета с валидацией.
    """
    if not message.text:
        logger.debug(
            f"⚠️ ТАРГЕТ-МАСТЕР: Пользователь {message.from_user.id} отправил пустое сообщение при вводе Gift ID")
        await safe_delete_message(message)
        return

    gift_id_input = message.text.strip()
    logger.info(f"🆔 ТАРГЕТ-МАСТЕР: Пользователь {message.from_user.id} ввел Gift ID: {gift_id_input}")

    # Удаляем сообщение пользователя после получения
    await safe_delete_message(message)

    # Валидация ID подарка
    validated_gift_id = validate_gift_id(gift_id_input)
    if validated_gift_id is None:
        logger.warning(f"❌ ТАРГЕТ-МАСТЕР: Невалидный Gift ID: {gift_id_input}")

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="☰ Меню", callback_data="main_menu")]
        ])

        error_text = ("🚫 <b>Ошибка валидации</b>\n\n"
                      "ID подарка должен быть длинным числом\n"
                      "Например: <code>6014591077976114307</code>\n\n"
                      "Попробуйте ещё раз или вернитесь в меню.")

        await edit_bot_message(message, state, error_text, kb)
        return

    # Проверяем доступность подарка (только базовая проверка)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="☰ Меню", callback_data="main_menu")]
    ])

    check_text = "🔍 <b>Проверка подарка...</b>\n\nПроверяю доступность подарка для перепродажи..."
    await edit_bot_message(message, state, check_text, kb)

    availability = await check_gift_availability(message.from_user.id, validated_gift_id)

    if not availability["available"]:
        error_msg = availability.get("error", "Подарки не найдены")
        logger.warning(f"⚠️ ТАРГЕТ-МАСТЕР: Подарок ID {validated_gift_id} недоступен: {error_msg}")

        error_text = (f"⚠️ <b>Подарок недоступен</b>\n\n"
                      f"ID: <code>{validated_gift_id}</code>\n"
                      f"Ошибка: {error_msg}\n\n"
                      "Попробуйте другой ID или вернитесь в меню.")

        await edit_bot_message(message, state, error_text, kb)
        return

    # Автоматически используем название подарка
    gift_name_found = availability.get("gift_name", "Unknown")
    total_found = availability["total_found"]

    await state.update_data(
        gift_id=validated_gift_id,
        gift_name=gift_name_found
    )

    success_text = (f"✅ <b>Подарок найден!</b>\n\n"
                    f"🎁 Название: {gift_name_found}\n"
                    f"📦 Доступно: {total_found:,} шт\n\n"
                    f"💰 Введите <b>максимальную цену</b> для этого таргета:")

    await edit_bot_message(message, state, success_text, kb)
    await state.set_state(ConfigWizard.target_max_price)


@wizard_states_router.message(ConfigWizard.target_max_price)
async def step_target_max_price(message: Message, state: FSMContext):
    """
    Обработка ввода максимальной цены и создание таргета.
    """
    if not message.text:
        logger.debug(f"⚠️ ТАРГЕТ-МАСТЕР: Пользователь {message.from_user.id} отправил пустое сообщение при вводе цены")
        await safe_delete_message(message)
        return

    price_input = message.text.strip()
    logger.info(f"💰 TARGETS: Пользователь {message.from_user.id} ввел цену: {price_input}")

    # Удаляем сообщение пользователя
    await safe_delete_message(message)

    try:
        max_price = int(price_input)
        if max_price <= 0:
            raise ValueError("Цена должна быть положительной")
    except ValueError as e:
        logger.warning(f"❌ ТАРГЕТ-МАСТЕР: Неверная цена '{price_input}': {e}")

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="☰ Меню", callback_data="main_menu")]
        ])

        error_text = ("🚫 <b>Неверная цена</b>\n\n"
                      "Введите положительное число (например: <code>15000</code>)")

        await edit_bot_message(message, state, error_text, kb)
        return

    # Простая проверка разумности цены
    if max_price > 1000000:
        logger.warning(f"⚠️ ТАРГЕТ-МАСТЕР: Слишком большая цена: {max_price}")

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="☰ Меню", callback_data="main_menu")]
        ])

        error_text = ("🚫 <b>Слишком большая цена</b>\n\n"
                      "Максимальная цена не может превышать 1,000,000 звезд")

        await edit_bot_message(message, state, error_text, kb)
        return

    data = await state.get_data()
    gift_id = data["gift_id"]
    gift_name = data["gift_name"]

    # Проверяем лимит таргетов
    config = await get_valid_config()
    current_targets = config.get("TARGETS", [])
    if len(current_targets) >= 20:
        logger.warning(f"⚠️ ТАРГЕТ-МАСТЕР: Достигнут лимит таргетов (20/20)")

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="☰ Меню", callback_data="main_menu")]
        ])

        error_text = ("🚫 <b>Лимит таргетов</b>\n\n"
                      "Достигнут максимальный лимит таргетов (20 шт)\n"
                      "Удалите ненужные таргеты.")

        await edit_bot_message(message, state, error_text, kb)
        await state.clear()
        return

    # Создаём таргет
    await add_target(config, str(gift_id), gift_name, max_price, save=True)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎯 Таргеты", callback_data="targets_menu")],
        [InlineKeyboardButton(text="☰ Меню", callback_data="main_menu")]
    ])

    success_text = (f"✅ <b>Таргет создан!</b>\n\n"
                    f"🎁 Название: {gift_name}\n"
                    f"🆔 ID: <code>{gift_id}</code>\n"
                    f"💰 Макс. цена: ★{max_price:,}\n\n"
                    f"Таргет добавлен в систему мониторинга.")

    logger.info(f"✅ TARGETS: Таргет успешно создан - {gift_name}")

    await edit_bot_message(message, state, success_text, kb)
    await state.clear()


# === Обработчики редактирования таргета ===

@wizard_states_router.message(ConfigWizard.edit_target_price)
async def step_edit_target_price(message: Message, state: FSMContext):
    """
    Обрабатывает ввод пользователем новой максимальной цены для таргета.
    """
    if not message.text:
        logger.debug(
            f"⚠️ РЕДАКТИРОВАНИЕ: Пользователь {message.from_user.id} отправил пустое сообщение при редактировании цены")
        await safe_delete_message(message)
        return

    price_input = message.text.strip()
    logger.info(f"💰 TARGETS: Пользователь {message.from_user.id} ввел новую цену: {price_input}")

    # Удаляем сообщение пользователя
    await safe_delete_message(message)

    data = await state.get_data()
    idx = data.get("target_index")
    if idx is None:
        logger.error("❌ РЕДАКТИРОВАНИЕ: Не найден индекс таргета в состоянии FSM")

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="☰ Меню", callback_data="main_menu")]
        ])

        error_text = "🚫 <b>Ошибка</b>\n\nНе выбран таргет для редактирования."
        await edit_bot_message(message, state, error_text, kb)
        await state.clear()
        return

    try:
        new_price = int(price_input)
        if new_price <= 0:
            raise ValueError("Цена должна быть положительной")
    except ValueError as e:
        logger.warning(f"❌ РЕДАКТИРОВАНИЕ: Неверная цена '{price_input}': {e}")

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="☰ Меню", callback_data="main_menu")]
        ])

        error_text = ("🚫 <b>Неверная цена</b>\n\n"
                      "Введите положительное число")

        await edit_bot_message(message, state, error_text, kb)
        return

    # Простая проверка разумности цены
    if new_price > 1000000:
        logger.warning(f"⚠️ РЕДАКТИРОВАНИЕ: Слишком большая цена: {new_price}")

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="☰ Меню", callback_data="main_menu")]
        ])

        error_text = ("🚫 <b>Слишком большая цена</b>\n\n"
                      "Максимальная цена не может превышать 1,000,000 звезд")

        await edit_bot_message(message, state, error_text, kb)
        return

    config = await get_valid_config()
    targets = config.get("TARGETS", [])
    if idx >= len(targets):
        logger.error(f"❌ РЕДАКТИРОВАНИЕ: Таргет #{idx} не найден (всего таргетов: {len(targets)})")

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="☰ Меню", callback_data="main_menu")]
        ])

        error_text = "🚫 <b>Ошибка</b>\n\nТаргет не найден."
        await edit_bot_message(message, state, error_text, kb)
        await state.clear()
        return

    target = targets[idx]
    gift_name = target.get('GIFT_NAME', '🎁')
    old_price = target.get('MAX_PRICE', 0)

    # Обновляем цену таргета
    await update_target(config, idx, max_price=new_price, save=True)

    logger.info(f"✅ TARGETS: Цена таргета #{idx} '{gift_name}' изменена: ★{old_price:,} → ★{new_price:,}")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎯 Таргеты", callback_data="targets_menu")],
        [InlineKeyboardButton(text="☰ Меню", callback_data="main_menu")]
    ])

    success_text = (f"✅ <b>Цена обновлена!</b>\n\n"
                    f"🎁 Таргет: {gift_name}\n"
                    f"💰 Было: ★{old_price:,}\n"
                    f"💰 Стало: ★{new_price:,}")

    await edit_bot_message(message, state, success_text, kb)
    await state.clear()


# === Обработчики изменения получателя ===

@wizard_states_router.message(ConfigWizard.recipient_user_id)
async def step_recipient_user_id(message: Message, state: FSMContext):
    """
    Обрабатывает ввод нового получателя подарков — ID или username.
    """
    if not message.text:
        logger.debug(
            f"⚠️ ПОЛУЧАТЕЛЬ: Пользователь {message.from_user.id} отправил пустое сообщение при вводе получателя")
        await safe_delete_message(message)
        return

    user_input = message.text.strip()

    # Удаляем сообщение пользователя
    await safe_delete_message(message)

    if user_input.startswith("@"):
        logger.debug(f"🔍 ПОЛУЧАТЕЛЬ: Определение типа для username: {user_input}")

        chat_type = await simple_get_chat_type(bot=message.bot, username=user_input)
        if chat_type == "channel":
            target_chat_id = user_input
            target_user_id = None
            target_type = "channel"
            logger.info(f"📥 TARGETS: Пользователь {message.from_user.id} установил канал: {user_input}")
        elif chat_type == "unknown":
            target_chat_id = user_input
            target_user_id = None
            target_type = "username"
            logger.info(f"📥 TARGETS: Пользователь {message.from_user.id} установил username: {user_input}")
        else:
            logger.warning(f"❌ ПОЛУЧАТЕЛЬ: Неподдерживаемый тип чата '{chat_type}' для {user_input}")

            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="☰ Меню", callback_data="main_menu")]
            ])

            error_text = ("🚫 <b>Неверный username</b>\n\n"
                          "Указан неправильный username канала.\n"
                          "Попробуйте ещё раз.")

            await edit_bot_message(message, state, error_text, kb)
            return
    elif user_input.isdigit():
        target_chat_id = None
        target_user_id = int(user_input)
        target_type = "user_id"
        logger.info(f"📥 TARGETS: Пользователь {message.from_user.id} установил User ID: {target_user_id}")
    else:
        logger.warning(f"❌ ПОЛУЧАТЕЛЬ: Неверный формат получателя: {user_input}")

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="☰ Меню", callback_data="main_menu")]
        ])

        error_text = ("🚫 <b>Неверный формат</b>\n\n"
                      "Введите ID пользователя или @username канала")

        await edit_bot_message(message, state, error_text, kb)
        return

    # Сохраняем новый получатель
    config = await get_valid_config()
    config["TARGET_USER_ID"] = target_user_id
    config["TARGET_CHAT_ID"] = target_chat_id
    config["TARGET_TYPE"] = target_type
    await save_config(config)

    # Формируем отображение получателя
    from services.config import get_target_display_local
    target_display = get_target_display_local(target_user_id, target_chat_id, message.from_user.id)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="☰ Меню", callback_data="main_menu")]
    ])

    success_text = (f"✅ <b>Получатель обновлён!</b>\n\n"
                    f"📥 Новый получатель: {target_display}")

    await edit_bot_message(message, state, success_text, kb)
    await state.clear()


def register_wizard_states_handlers(dp) -> None:
    """
    Регистрирует все хендлеры FSM состояний.
    """
    dp.include_router(wizard_states_router)
    logger.debug("📝 FSM: Обработчики FSM состояний зарегистрированы")