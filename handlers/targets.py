# handlers/targets.py
"""
Модуль хендлеров для управления таргетами - единое сообщение.

Этот модуль содержит функции для:
- Отображения меню управления таргетами.
- Создания, редактирования и удаления таргетов.
- Валидации и сохранения параметров таргетов.

Основные функции:
- targets_menu: Показывает меню управления таргетами.
- on_targets_menu: Обработчик кнопки "Таргеты".
- target_add_handlers: Группа обработчиков добавления таргетов.
- target_edit_handlers: Группа обработчиков редактирования таргетов.
"""

# --- Стандартные библиотеки ---
import logging

# --- Сторонние библиотеки ---
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

# --- Внутренние модули ---
from services.config import get_valid_config, remove_target, update_target
from services.menu import safe_edit_menu
from handlers.wizard_states import ConfigWizard

logger = logging.getLogger(__name__)
targets_router = Router()


async def targets_menu(message: Message) -> None:
    """
    Показывает пользователю главное меню управления таргетами в едином сообщении.
    Отображает список всех таргетов и предоставляет кнопки для их редактирования или добавления нового таргета.
    """
    logger.debug("🎯 ТАРГЕТЫ: Формирование меню управления таргетами")

    config = await get_valid_config()
    targets = config.get("TARGETS", [])

    # Формируем клавиатуру таргетов
    keyboard = []
    for idx, target in enumerate(targets):
        gift_name = target.get('GIFT_NAME', '🎁')
        max_price = target.get('MAX_PRICE', 0)
        enabled = target.get('ENABLED', True)
        status_icon = "✅" if enabled else "🔕"

        # Кнопка для редактирования таргета
        btn = InlineKeyboardButton(
            text=f"{status_icon} {gift_name} ★{max_price:,}",
            callback_data=f"target_edit_{idx}"
        )
        keyboard.append([btn])

    # Проверяем лимит таргетов (максимум 20)
    max_targets = 20
    if len(targets) < max_targets:
        keyboard.append([InlineKeyboardButton(text="➕ Добавить таргет", callback_data="target_add")])
    else:
        keyboard.append([InlineKeyboardButton(text="🚫 Лимит таргетов (20/20)", callback_data="target_limit_reached")])

    # Кнопка назад
    keyboard.append([InlineKeyboardButton(text="☰ Меню", callback_data="main_menu")])

    # Формируем текст меню
    lines = []
    enabled_count = len([t for t in targets if t.get('ENABLED', True)])

    if targets:
        lines.append(f"🎯 <b>Всего таргетов:</b> {len(targets)}/{max_targets}")
        lines.append(f"✅ <b>Активных:</b> {enabled_count}")
        lines.append("")

        for idx, target in enumerate(targets, 1):
            gift_name = target.get('GIFT_NAME', '🎁')
            gift_id = target.get('GIFT_ID', 'N/A')
            max_price = target.get('MAX_PRICE', 0)
            enabled = target.get('ENABLED', True)
            status_icon = "✅" if enabled else "🔕"

            if len(targets) == 1:
                line = f"{status_icon} <b>{gift_name}</b> (ID: {gift_id}) до ★{max_price:,}"
            elif idx == 1:
                line = f"┌{status_icon} <b>{gift_name}</b> (ID: {gift_id}) до ★{max_price:,}"
            elif idx == len(targets):
                line = f"└{status_icon} <b>{gift_name}</b> (ID: {gift_id}) до ★{max_price:,}"
            else:
                line = f"├{status_icon} <b>{gift_name}</b> (ID: {gift_id}) до ★{max_price:,}"

            lines.append(line)
        text_targets = "\n".join(lines)
    else:
        text_targets = f"🎯 <b>Таргетов пока нет (0/{max_targets})</b>\n\nДобавьте таргет, чтобы бот начал мониторить конкретные подарки по вашим ценовым лимитам."

    kb = InlineKeyboardMarkup(inline_keyboard=keyboard)

    logger.debug(f"🎯 ТАРГЕТЫ: Отображение меню - всего: {len(targets)}, активных: {enabled_count}")

    await safe_edit_menu(
        message,
        f"{text_targets}\n\n"
        "👉 <b>Нажмите</b> на таргет чтобы изменить его.\n"
        "🎯 <b>Таргет</b> — это конкретный подарок с максимальной ценой для покупки.",
        kb
    )


@targets_router.callback_query(F.data == "targets_menu")
async def on_targets_menu(call: CallbackQuery):
    """
    Обрабатывает нажатие на кнопку "Таргеты" или переход к списку таргетов.
    Проверяет настройку отправителя и получателя перед доступом к таргетам.
    """
    logger.info(f"🎯 TARGETS: Пользователь {call.from_user.id} перешёл по кнопке \"Таргеты\"")

    config = await get_valid_config()

    # Проверяем настройку отправителя
    userbot = config.get("USERBOT", {})
    sender_configured = bool(
        userbot.get("API_ID") and
        userbot.get("API_HASH") and
        userbot.get("PHONE")
    )

    # Проверяем настройку получателя
    recipient_configured = bool(
        config.get("TARGET_USER_ID") or
        config.get("TARGET_CHAT_ID")
    )

    # Если отправитель или получатель не настроены
    if not sender_configured or not recipient_configured:
        missing_items = []
        if not sender_configured:
            missing_items.append("Отправитель")
        if not recipient_configured:
            missing_items.append("Получатель")

        missing_text = " и ".join(missing_items)
        alert_text = f"⚠️ Сначала настройте: {missing_text}"

        logger.warning(f"⚠️ ТАРГЕТЫ: Доступ к таргетам заблокирован - не настроены: {missing_text}")
        await call.answer(alert_text, show_alert=True)
        return

    # Если все настроено, показываем меню таргетов
    await targets_menu(call.message)
    await call.answer()


@targets_router.callback_query(F.data == "target_limit_reached")
async def on_target_limit_reached(call: CallbackQuery):
    """
    Обрабатывает нажатие на кнопку лимита таргетов.
    """
    logger.warning(f"⚠️ ТАРГЕТЫ: Пользователь {call.from_user.id} достиг лимита таргетов (20)")
    await call.answer("🚫 Достигнут максимальный лимит таргетов (20 шт). Удалите ненужные таргеты.", show_alert=True)


def target_text(target: dict, idx: int) -> str:
    """
    Формирует текстовое описание параметров таргета по его данным.
    """
    gift_name = target.get('GIFT_NAME', '🎁')
    gift_id = target.get('GIFT_ID', 'N/A')
    max_price = target.get('MAX_PRICE', 0)
    enabled = target.get('ENABLED', True)
    status_text = "✅ Включён" if enabled else "🔕 Выключен"

    return (f"✏️ <b>Редактирование таргета {idx + 1}</b>:\n\n"
            f"┌🎁 <b>Название:</b> {gift_name}\n"
            f"├🆔 <b>ID подарка:</b> <code>{gift_id}</code>\n"
            f"├💰 <b>Макс. цена:</b> ★{max_price:,}\n"
            f"└🔘 <b>Статус:</b> {status_text}")


def target_edit_keyboard(idx: int, enabled: bool) -> InlineKeyboardMarkup:
    """
    Создаёт инлайн-клавиатуру для быстрого редактирования параметров выбранного таргета.
    """
    toggle_text = "🔕 Выключить" if enabled else "✅ Включить"
    toggle_callback = f"target_toggle_{idx}"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💰 Цена", callback_data=f"edit_target_price_{idx}"),
                InlineKeyboardButton(text=toggle_text, callback_data=toggle_callback)
            ],
            [
                InlineKeyboardButton(text="🗑 Удалить", callback_data=f"target_delete_{idx}")
            ],
            [
                InlineKeyboardButton(text="⬅️ Назад", callback_data="targets_menu"),
                InlineKeyboardButton(text="☰ Меню", callback_data="main_menu")
            ]
        ]
    )


@targets_router.callback_query(lambda c: c.data.startswith("target_edit_"))
async def on_target_edit(call: CallbackQuery, state: FSMContext):
    """
    Открывает экран подробного редактирования конкретного таргета.
    """
    idx = int(call.data.split("_")[-1])

    logger.info(f"✏️ TARGETS: Пользователь {call.from_user.id} редактирует таргет #{idx}")

    config = await get_valid_config()
    targets = config.get("TARGETS", [])

    if idx >= len(targets):
        logger.error(f"❌ ТАРГЕТЫ: Таргет #{idx} не найден (всего таргетов: {len(targets)})")
        await call.answer("🚫 Таргет не найден.", show_alert=True)
        return

    target = targets[idx]
    enabled = target.get('ENABLED', True)
    gift_name = target.get('GIFT_NAME', '🎁')

    logger.debug(f"✏️ ТАРГЕТЫ: Открытие редактирования таргета #{idx}: {gift_name}")

    await state.update_data(target_index=idx)

    await safe_edit_menu(
        call.message,
        target_text(target, idx),
        target_edit_keyboard(idx, enabled)
    )
    await call.answer()


@targets_router.callback_query(lambda c: c.data.startswith("target_toggle_"))
async def on_target_toggle(call: CallbackQuery):
    """
    Переключает статус активности таргета (включён/выключен).
    """
    idx = int(call.data.split("_")[-1])

    logger.info(f"🔄 TARGETS: Пользователь {call.from_user.id} переключает статус таргета #{idx}")

    config = await get_valid_config()
    targets = config.get("TARGETS", [])

    if idx >= len(targets):
        logger.error(f"❌ ТАРГЕТЫ: Таргет #{idx} не найден для переключения статуса")
        await call.answer("🚫 Таргет не найден.", show_alert=True)
        return

    target = targets[idx]
    old_enabled = target.get('ENABLED', True)
    new_enabled = not old_enabled
    gift_name = target.get('GIFT_NAME', '🎁')

    await update_target(config, idx, enabled=new_enabled, save=True)

    logger.info(f"✅ ТАРГЕТЫ: Статус таргета #{idx} '{gift_name}' изменен: {old_enabled} → {new_enabled}")

    await safe_edit_menu(
        call.message,
        target_text(target, idx),
        target_edit_keyboard(idx, new_enabled)
    )

    status_text = "включён" if new_enabled else "выключен"
    await call.answer(f"Таргет {status_text}")


@targets_router.callback_query(F.data == "target_add")
async def on_target_add(call: CallbackQuery, state: FSMContext):
    """
    Запускает процесс добавления нового таргета в едином сообщении.
    """
    logger.info(f"➕ TARGETS: Пользователь {call.from_user.id} перешёл по кнопке \"Добавить таргет\"")

    # Проверяем лимит таргетов
    config = await get_valid_config()
    current_targets = config.get("TARGETS", [])

    if len(current_targets) >= 20:
        logger.warning(f"⚠️ ТАРГЕТЫ: Попытка добавить таргет при достижении лимита (20/20)")
        await call.answer("🚫 Достигнут максимальный лимит таргетов (20 шт)", show_alert=True)
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="☰ Меню", callback_data="main_menu")]
    ])

    text = ("🆔 <b>Добавление нового таргета</b>\n\n"
            "Введите <b>ID подарка</b>:\n\n"
            "Например: <code>6014591077976114307</code>\n\n"
            "/cancel — отмена")

    await safe_edit_menu(call.message, text, kb)
    # Сохраняем ID сообщения для последующего редактирования
    await state.update_data(bot_message_id=call.message.message_id)
    await state.set_state(ConfigWizard.target_gift_id)
    await call.answer()


# === Редактирование полей таргета ===

@targets_router.callback_query(lambda c: c.data.startswith("edit_target_price_"))
async def edit_target_price(call: CallbackQuery, state: FSMContext):
    """
    Запускает FSM для редактирования цены таргета.
    """
    idx = int(call.data.split("_")[-1])

    logger.info(f"💰 TARGETS: Пользователь {call.from_user.id} редактирует цену таргета #{idx}")

    config = await get_valid_config()
    targets = config.get("TARGETS", [])

    if idx >= len(targets):
        logger.error(f"❌ ТАРГЕТЫ: Таргет #{idx} не найден для редактирования цены")
        await call.answer("🚫 Таргет не найден.", show_alert=True)
        return

    target = targets[idx]
    gift_name = target.get('GIFT_NAME', '🎁')
    current_price = target.get('MAX_PRICE', 0)

    logger.debug(f"💰 ТАРГЕТЫ: Текущая цена таргета #{idx} '{gift_name}': ★{current_price:,}")

    await state.update_data(target_index=idx)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="☰ Меню", callback_data="main_menu")]
    ])

    text = (f"💰 <b>Изменение цены таргета</b>\n\n"
            f"🎁 Таргет: {gift_name}\n"
            f"💰 Текущая цена: ★{current_price:,}\n\n"
            f"Введите новую <b>максимальную цену</b>:\n"
            f"Например: <code>15000</code>\n\n"
            "/cancel — отмена")

    await safe_edit_menu(call.message, text, kb)
    # Сохраняем ID сообщения для последующего редактирования
    await state.update_data(bot_message_id=call.message.message_id)
    await state.set_state(ConfigWizard.edit_target_price)
    await call.answer()


# === Удаление таргетов ===

@targets_router.callback_query(lambda c: c.data.startswith("target_delete_"))
async def on_target_delete_confirm(call: CallbackQuery):
    """
    Запрашивает подтверждение удаления таргета.
    """
    idx = int(call.data.split("_")[-1])

    logger.info(f"🗑️ TARGETS: Пользователь {call.from_user.id} запрашивает удаление таргета #{idx}")

    config = await get_valid_config()
    targets = config.get("TARGETS", [])

    if idx >= len(targets):
        logger.error(f"❌ ТАРГЕТЫ: Таргет #{idx} не найден для удаления")
        await call.answer("🚫 Таргет не найден.", show_alert=True)
        return

    target = targets[idx]
    gift_name = target.get('GIFT_NAME', '🎁')
    max_price = target.get('MAX_PRICE', 0)
    gift_id = target.get('GIFT_ID', 'N/A')

    logger.debug(f"🗑️ ТАРГЕТЫ: Подтверждение удаления таргета #{idx}: {gift_name} (★{max_price:,})")

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да", callback_data=f"confirm_target_delete_{idx}"),
                InlineKeyboardButton(text="❌ Нет", callback_data=f"cancel_target_delete_{idx}"),
            ]
        ]
    )

    message = (f"┌🎁 <b>Название:</b> {gift_name}\n"
               f"├💰 <b>Макс. цена:</b> ★{max_price:,}\n"
               f"└🆔 <b>ID:</b> <code>{gift_id}</code>")

    text = f"⚠️ <b>Удаление таргета</b>\n\nВы уверены, что хотите удалить таргет?\n\n{message}"

    await safe_edit_menu(call.message, text, kb)
    await call.answer()


@targets_router.callback_query(lambda c: c.data.startswith("confirm_target_delete_"))
async def on_target_delete_final(call: CallbackQuery):
    """
    Окончательно удаляет таргет после подтверждения.
    """
    idx = int(call.data.split("_")[-1])

    logger.info(f"🗑️ TARGETS: Пользователь {call.from_user.id} подтверждает удаление таргета #{idx}")

    config = await get_valid_config()
    targets = config.get("TARGETS", [])

    if idx >= len(targets):
        logger.error(f"❌ ТАРГЕТЫ: Таргет #{idx} не найден для окончательного удаления")
        await call.answer("🚫 Таргет не найден.", show_alert=True)
        return

    target = targets[idx]
    gift_name = target.get('GIFT_NAME', '🎁')
    gift_id = target.get('GIFT_ID', 'N/A')
    max_price = target.get('MAX_PRICE', 0)

    await remove_target(config, idx, save=True)

    logger.info(f"✅ ТАРГЕТЫ: Таргет #{idx} '{gift_name}' (ID: {gift_id}, ★{max_price:,}) успешно удален")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎯 Таргеты", callback_data="targets_menu")],
        [InlineKeyboardButton(text="☰ Меню", callback_data="main_menu")]
    ])

    text = f"✅ <b>Таргет удалён!</b>\n\nТаргет <b>{gift_name}</b> успешно удалён из системы."

    await safe_edit_menu(call.message, text, kb)
    await call.answer()


@targets_router.callback_query(lambda c: c.data.startswith("cancel_target_delete_"))
async def on_target_delete_cancel(call: CallbackQuery):
    """
    Отмена удаления таргета.
    """
    idx = int(call.data.split("_")[-1])

    logger.info(f"↩️ TARGETS: Пользователь {call.from_user.id} отменил удаление таргета #{idx}")

    config = await get_valid_config()
    targets = config.get("TARGETS", [])

    if idx >= len(targets):
        logger.error(f"❌ ТАРГЕТЫ: Таргет #{idx} не найден при отмене удаления")
        await call.answer("🚫 Таргет не найден.", show_alert=True)
        return

    target = targets[idx]
    enabled = target.get('ENABLED', True)

    await safe_edit_menu(
        call.message,
        target_text(target, idx),
        target_edit_keyboard(idx, enabled)
    )
    await call.answer("Отменено.")


def register_targets_handlers(dp) -> None:
    """
    Регистрирует все хендлеры, связанные с управлением таргетами.
    """
    dp.include_router(targets_router)
    logger.debug("📝 ТАРГЕТЫ: Обработчики таргетов зарегистрированы")