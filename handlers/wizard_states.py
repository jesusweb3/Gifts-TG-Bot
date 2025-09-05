# handlers/wizard_states.py
"""
Модуль FSM состояний и общих утилит для wizard handlers (система таргетов).

Этот модуль содержит:
- Определения всех FSM состояний для пошагового редактирования.
- Общие утилиты для обработки отмены и редактирования сообщений.
- Обработчики пошаговых состояний создания и редактирования таргетов.
- Обработчики для изменения получателя подарков.

Основные классы и функции:
- ConfigWizard: Класс состояний FSM для пошагового редактирования.
- try_cancel: Универсальная функция для обработки отмены.
- safe_edit_text: Безопасное редактирование сообщений.
"""

# --- Стандартные библиотеки ---
import logging

# --- Сторонние библиотеки ---
from aiogram import Router, Bot
from aiogram.types import Message, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest

# --- Внутренние модули ---
from services.config import get_valid_config, save_config, add_target, update_target
from services.menu import update_menu
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


async def try_cancel(message: Message, state: FSMContext) -> bool:
    """
    Проверяет, ввёл ли пользователь команду /cancel для отмены текущего шага мастера.
    Если команда введена, очищает состояние FSM, отправляет сообщение об отмене и обновляет главное меню пользователя.
    """
    if message.text and message.text.strip().lower() == "/cancel":
        await state.clear()
        await message.answer("🚫 Действие отменено.")
        await update_menu(bot=message.bot, chat_id=message.chat.id, user_id=message.from_user.id,
                          message_id=message.message_id)
        return True
    return False


async def safe_edit_text(message: Message, text: str, reply_markup: InlineKeyboardMarkup = None) -> bool:
    """
    Безопасно редактирует текст сообщения, игнорируя ошибки "нельзя редактировать" и "сообщение не найдено".
    """
    try:
        await message.edit_text(text, reply_markup=reply_markup)
        return True
    except TelegramBadRequest as e:
        logger.error(f"Ошибка редактирования сообщения: {e}")
        if "message can't be edited" in str(e) or "message to edit not found" in str(e):
            return False
        else:
            raise


async def simple_get_chat_type(bot: Bot, username: str) -> str:
    """
    Упрощенная функция определения типа чата по username.
    """
    if not username.startswith("@"):
        username = "@" + username
    try:
        chat = await bot.get_chat(username)
        if chat.type == "private":
            return "user" if not getattr(chat, "is_bot", False) else "bot"
        elif chat.type == "channel":
            return "channel"
        else:
            return "group"
    except Exception as e:
        logger.info(f"Не удалось получить информацию о чате {username}: {e}")
        return "unknown"


# === Обработчики создания таргета ===

@wizard_states_router.message(ConfigWizard.target_gift_id)
async def step_target_gift_id(message: Message, state: FSMContext):
    """
    Обработка ввода ID подарка для нового таргета с валидацией.
    """
    if await try_cancel(message, state):
        return

    if not message.text:
        await message.answer("🚫 Поддерживается только текстовый ввод данных.\n\n/cancel — отмена")
        return

    gift_id_input = message.text.strip()

    # Валидация ID подарка
    validated_gift_id = validate_gift_id(gift_id_input)
    if validated_gift_id is None:
        await message.answer("🚫 ID подарка должен быть длинным числом (например: 6014591077976114307). Попробуйте ещё раз.\n\n/cancel — отмена")
        return

    # Проверяем доступность подарка
    await message.answer("🔍 Проверяю доступность подарка...")

    availability = await check_gift_availability(message.from_user.id, validated_gift_id)

    if not availability["available"]:
        error_msg = availability.get("error", "Подарки не найдены")
        await message.answer(f"⚠️ Подарок с ID {validated_gift_id} недоступен:\n{error_msg}\n\n"
                             "Попробуйте другой ID или /cancel для отмены")
        return

    # Автоматически используем название подарка
    gift_name_found = availability.get("gift_name", "Unknown")
    total_found = availability["total_found"]

    await state.update_data(
        gift_id=validated_gift_id,
        gift_name=gift_name_found
    )

    await message.answer(f"✅ Подарок найден!\n"
                         f"🎁 Название: {gift_name_found}\n"
                         f"📦 Доступно на перепродаже: {total_found:,} шт\n\n"
                         f"💰 Введите <b>максимальную цену</b> для этого таргета:\n\n"
                         f"/cancel — отмена")

    await state.set_state(ConfigWizard.target_max_price)


@wizard_states_router.message(ConfigWizard.target_max_price)
async def step_target_max_price(message: Message, state: FSMContext):
    """
    Обработка ввода максимальной цены и создание таргета.
    """
    if await try_cancel(message, state):
        return

    if not message.text:
        await message.answer("🚫 Поддерживается только текстовый ввод данных.\n\n/cancel — отмена")
        return

    try:
        max_price = int(message.text.strip())
        if max_price <= 0:
            raise ValueError
    except ValueError:
        await message.answer("🚫 Введите положительное число. Попробуйте ещё раз.\n\n/cancel — отмена")
        return

    # Простая проверка разумности цены
    if max_price > 1000000:
        await message.answer("🚫 Слишком большая цена (больше 1,000,000 звезд). Попробуйте ещё раз.\n\n/cancel — отмена")
        return

    data = await state.get_data()
    gift_id = data["gift_id"]
    gift_name = data["gift_name"]

    # Проверяем лимит таргетов
    config = await get_valid_config()
    current_targets = config.get("TARGETS", [])
    if len(current_targets) >= 20:
        await message.answer("🚫 Достигнут максимальный лимит таргетов (20 шт). Удалите ненужные таргеты.")
        await state.clear()
        return

    # Создаём таргет
    await add_target(config, str(gift_id), gift_name, max_price, save=True)

    await message.answer(f"✅ <b>Таргет создан!</b>\n\n"
                         f"🎁 Название: {gift_name}\n"
                         f"🆔 ID подарка: <code>{gift_id}</code>\n"
                         f"💰 Макс. цена: ★{max_price:,}\n\n"
                         f"Таргет добавлен в систему мониторинга.")

    await state.clear()

    # Возвращаемся в меню таргетов
    from handlers.targets import targets_menu
    await targets_menu(message, message.from_user.id)


# === Обработчики редактирования таргета ===

@wizard_states_router.message(ConfigWizard.edit_target_price)
async def step_edit_target_price(message: Message, state: FSMContext):
    """
    Обрабатывает ввод пользователем новой максимальной цены для таргета.
    """
    if await try_cancel(message, state):
        return

    if not message.text:
        await message.answer("🚫 Поддерживается только текстовый ввод данных.\n\n/cancel — отмена")
        return

    data = await state.get_data()
    idx = data.get("target_index")
    if idx is None:
        await message.answer("Ошибка: не выбран таргет для редактирования.")
        await state.clear()
        return

    try:
        new_price = int(message.text.strip())
        if new_price <= 0:
            raise ValueError
    except ValueError:
        await message.answer("🚫 Введите положительное число. Попробуйте ещё раз.\n\n/cancel — отмена")
        return

    # Простая проверка разумности цены
    if new_price > 1000000:
        await message.answer("🚫 Слишком большая цена (больше 1,000,000 звезд). Попробуйте ещё раз.\n\n/cancel — отмена")
        return

    config = await get_valid_config()
    targets = config.get("TARGETS", [])
    if idx >= len(targets):
        await message.answer("Ошибка: таргет не найден.")
        await state.clear()
        return

    target = targets[idx]
    gift_name = target.get('GIFT_NAME', '🎁')
    old_price = target.get('MAX_PRICE', 0)

    # Обновляем цену таргета
    await update_target(config, idx, max_price=new_price, save=True)

    await message.answer(f"✅ Цена таргета <b>{gift_name}</b> обновлена:\n"
                         f"Было: ★{old_price:,}\n"
                         f"Стало: ★{new_price:,}")

    await state.clear()

    # Возвращаемся в меню таргетов
    from handlers.targets import targets_menu
    await targets_menu(message, message.from_user.id)


# === Обработчики изменения получателя ===

@wizard_states_router.message(ConfigWizard.recipient_user_id)
async def step_recipient_user_id(message: Message, state: FSMContext):
    """
    Обрабатывает ввод нового получателя подарков — ID или username.
    """
    if await try_cancel(message, state):
        return

    if not message.text:
        await message.answer("🚫 Поддерживается только текстовый ввод данных.\n\n/cancel — отмена")
        return

    user_input = message.text.strip()

    if user_input.startswith("@"):
        chat_type = await simple_get_chat_type(bot=message.bot, username=user_input)
        if chat_type == "channel":
            target_chat_id = user_input
            target_user_id = None
            target_type = "channel"
        elif chat_type == "unknown":
            target_chat_id = user_input
            target_user_id = None
            target_type = "username"
        else:
            await message.answer(
                "🚫 Вы указали неправильный <b>username канала</b>. Попробуйте ещё раз.\n\n/cancel — отмена")
            return
    elif user_input.isdigit():
        target_chat_id = None
        target_user_id = int(user_input)
        target_type = "user_id"
    else:
        await message.answer("🚫 Введите ID или @username канала. Попробуйте ещё раз.\n\n/cancel — отмена")
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

    await message.answer(f"✅ <b>Получатель обновлён!</b>\n\n"
                         f"📥 Новый получатель: {target_display}")

    await state.clear()
    await update_menu(bot=message.bot, chat_id=message.chat.id, user_id=message.from_user.id,
                      message_id=message.message_id)


def register_wizard_states_handlers(dp) -> None:
    """
    Регистрирует все хендлеры FSM состояний.
    """
    dp.include_router(wizard_states_router)