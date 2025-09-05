# main.py
"""
Главный модуль приложения Telegram Gifts Bot (система таргетов) - единое сообщение.

Этот модуль содержит функции для:
- Запуска асинхронного приложения.
- Настройки и проверки конфигурации.
- Регистрации хендлеров.
- Запуска фоновых задач.

Основные функции:
- main: Асинхронная точка входа в приложение.
- gift_purchase_worker: Фоновый воркер для покупки подарков по таргетам.
"""

# --- Стандартные библиотеки ---
import asyncio
import logging
import sys

# --- Сторонние библиотеки ---
from aiogram import Bot, Dispatcher
from aiogram.utils.backoff import BackoffConfig
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from pyrogram.errors import SecurityCheckMismatch

# --- Внутренние модули ---
from services.config import (
    ensure_config,
    save_config,
    get_valid_config,
    get_target_display_local,
    update_config_from_env,
    VERSION,
    PURCHASE_COOLDOWN,
    MORE_LOGS,
    DEFAULT_BOT_DELAY
)
from services.menu import send_main_menu
from services.balance import refresh_balance
from services.gifts_manager import userbot_targets_updater, get_all_available_target_gifts
from services.buy_userbot import buy_resold_gift_userbot, validate_gift_purchase
from services.userbot import try_start_userbot_from_config, is_userbot_active
from handlers.targets import register_targets_handlers
from handlers.sender_management import register_sender_handlers
from handlers.wizard_states import register_wizard_states_handlers
from handlers.handlers_main import register_main_handlers
from utils.logging import setup_logging
from utils.env_loader import get_env_variable

setup_logging()
logger = logging.getLogger(__name__)

# Hardcoded user credentials - упрощение для личного использования
TOKEN = get_env_variable("TELEGRAM_BOT_TOKEN")
USER_ID_STR = get_env_variable("TELEGRAM_USER_ID", "0")
USER_ID = int(USER_ID_STR) if USER_ID_STR else 0

if not TOKEN or not USER_ID:
    logger.critical("TELEGRAM_BOT_TOKEN и TELEGRAM_USER_ID должны быть заданы в переменных окружения")
    sys.exit(1)


async def gift_purchase_worker(bot: Bot) -> None:
    """
    Фоновый воркер для покупки подарков по системе таргетов.
    Мониторит доступные подарки по каждому таргету и покупает те, которые соответствуют условиям.
    Использует единое сообщение для уведомлений.

    :param bot: Экземпляр бота aiogram
    :return: None
    """
    await refresh_balance()
    logger.info("Запущен воркер покупки подарков по таргетам")

    while True:
        try:
            config = await get_valid_config()

            if not config["ACTIVE"]:
                await asyncio.sleep(1)
                continue

            # Проверяем что отправитель активен
            if not is_userbot_active(USER_ID):
                logger.warning("Отправитель неактивен, останавливаем покупки")
                config["ACTIVE"] = False
                await save_config(config)

                text = ("⚠️ <b>Отправитель неактивен</b>\n\n"
                        "📤 Настройте отправитель для продолжения работы!\n"
                        "🚦 Статус изменён на 🔴 (неактивен).")

                # Отправляем уведомление с главным меню
                await bot.send_message(chat_id=USER_ID, text=text)
                await send_main_menu(bot=bot, chat_id=USER_ID, user_id=USER_ID)

                await asyncio.sleep(5)
                continue

            target_user_id = config.get("TARGET_USER_ID")
            target_chat_id = config.get("TARGET_CHAT_ID")
            targets = config.get("TARGETS", [])
            enabled_targets = [t for t in targets if t.get("ENABLED", True)]

            if not enabled_targets:
                if MORE_LOGS:
                    logger.info("Нет активных таргетов для мониторинга")
                await asyncio.sleep(DEFAULT_BOT_DELAY)
                continue

            # Проверяем получателя
            if not target_user_id and not target_chat_id:
                logger.warning("Получатель не настроен")
                config["ACTIVE"] = False
                await save_config(config)

                text = ("⚠️ <b>Получатель не настроен</b>\n\n"
                        "📥 Настройте получателя для продолжения работы!\n"
                        "🚦 Статус изменён на 🔴 (неактивен).")

                # Отправляем уведомление с главным меню
                await bot.send_message(chat_id=USER_ID, text=text)
                await send_main_menu(bot=bot, chat_id=USER_ID, user_id=USER_ID)

                await asyncio.sleep(5)
                continue

            # Получаем список всех доступных подарков для таргетов из кеша
            available_target_gifts = get_all_available_target_gifts(USER_ID)

            if MORE_LOGS:
                logger.info(f"Доступно подарков для таргетов: {len(available_target_gifts)}")

            if not available_target_gifts:
                if MORE_LOGS:
                    logger.info("Нет доступных подарков по таргетам")
                await asyncio.sleep(DEFAULT_BOT_DELAY)
                continue

            purchased_any = False

            # Проверяем каждый доступный подарок для таргетов
            for target_gift in available_target_gifts:
                target_index = target_gift.get("target_index")
                target_gift_name = target_gift.get("target_gift_name", "🎁")
                target_max_price = target_gift.get("target_max_price", 0)
                gift_price = target_gift.get("price", 0)
                gift_link = target_gift.get("link", "")
                gift_name = target_gift.get("name", "Unknown")

                if not gift_link:
                    if MORE_LOGS:
                        logger.warning(f"У подарка таргета {target_index} нет ссылки")
                    continue

                # Проверяем что цена в пределах лимита (дополнительная проверка)
                if gift_price > target_max_price:
                    if MORE_LOGS:
                        logger.warning(f"Цена подарка {gift_price} превышает лимит таргета {target_max_price}")
                    continue

                # Валидируем данные перед покупкой
                if not await validate_gift_purchase(
                        gift_data=target_gift,
                        target_user_id=target_user_id,
                        target_chat_id=target_chat_id,
                        max_price=target_max_price
                ):
                    logger.warning(f"Валидация не прошла для подарка таргета {target_index}")
                    continue

                # Пытаемся купить подарок
                logger.info(f"Найден подходящий подарок для таргета {target_index}: {target_gift_name}")
                logger.info(f"Подарок: {gift_name} за ★{gift_price:,} (лимит ★{target_max_price:,})")

                success = await buy_resold_gift_userbot(
                    session_user_id=USER_ID,
                    gift_link=gift_link,
                    target_user_id=target_user_id,
                    target_chat_id=target_chat_id,
                    expected_price=gift_price
                )

                if success:
                    target_display = get_target_display_local(target_user_id, target_chat_id, USER_ID)
                    sender_config = config.get("USERBOT", {})
                    sender_name = sender_config.get("FIRST_NAME", "Отправитель")

                    text = (f"✅ <b>Подарок отправлен!</b>\n\n"
                            f"🎯 Таргет: {target_gift_name}\n"
                            f"🎁 Подарок: {gift_name} за ★{gift_price:,}\n"
                            f"💰 Лимит: ★{target_max_price:,}\n"
                            f"📤 Отправитель: {sender_name}\n"
                            f"📥 Получатель: {target_display}\n"
                            f"🔗 Ссылка: {gift_link}")

                    # Отправляем уведомление об успешной покупке
                    await bot.send_message(chat_id=USER_ID, text=text)
                    # Отправляем обновленное главное меню
                    await send_main_menu(bot=bot, chat_id=USER_ID, user_id=USER_ID)

                    await refresh_balance()
                    purchased_any = True

                    # Делаем паузу между покупками
                    logger.info(f"Пауза {PURCHASE_COOLDOWN} сек между покупками")
                    await asyncio.sleep(PURCHASE_COOLDOWN)

                    # Прерываем цикл после успешной покупки, чтобы обновить данные
                    break
                else:
                    logger.warning(f"Не удалось купить подарок для таргета {target_index}: {gift_name}")

            # Если ни один подарок не удалось купить, возможно проблема с балансом или доступом
            if not purchased_any and available_target_gifts:
                # Проверяем баланс
                current_balance = await refresh_balance()
                min_price = min(gift.get("price", 0) for gift in available_target_gifts)

                if current_balance < min_price:
                    logger.error(
                        f"Недостаточно баланса для покупки подарков (баланс: {current_balance}, мин. цена: {min_price})")
                    config["ACTIVE"] = False
                    await save_config(config)

                    text = (f"⚠️ <b>Недостаточно звезд</b>\n\n"
                            f"💰 Баланс: {current_balance} ★\n"
                            f"💸 Требуется минимум: {min_price} ★\n"
                            f"🚦 Статус изменён на 🔴 (неактивен).")

                    # Отправляем уведомление с главным меню
                    await bot.send_message(chat_id=USER_ID, text=text)
                    await send_main_menu(bot=bot, chat_id=USER_ID, user_id=USER_ID)
                else:
                    if MORE_LOGS:
                        logger.info("Доступные подарки есть, но покупка не удалась (возможно, уже куплены)")

        except Exception as e:
            logger.error(f"Ошибка в gift_purchase_worker: {e}")

        await asyncio.sleep(DEFAULT_BOT_DELAY)


async def main() -> None:
    """
    Асинхронная точка входа в приложение (система таргетов) - единое сообщение.

    - Проверяет конфигурационный файл (config.json)
    - Создаёт HTTP-сессию и объект бота
    - Регистрирует хендлеры
    - Запускает отправитель (если он настроен)
    - Запускает фоновые задачи (покупки через отправитель, обновление кеша таргетов)
    - Запускает polling через aiogram Dispatcher

    :return: None
    """
    logger.info(f"Telegram Gifts Bot v{VERSION} запущен. Начинаем инициализацию...")

    # Проверяем наличие параметра CONFIG_DATA
    env_config_data = get_env_variable("CONFIG_DATA", None)
    if env_config_data is not None:
        await update_config_from_env(config_data=env_config_data)

    # Проверяем конфигурацию
    await ensure_config()

    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())

    # Простая защита: отключение громоздких traceback'ов SecurityCheckMismatch
    def _loop_exception_handler(event_loop, context):
        exception = context.get("exception")
        if isinstance(exception, SecurityCheckMismatch):
            logger.warning("Pyrogram SecurityCheckMismatch — подробный traceback отключён.")
            return
        event_loop.default_exception_handler(context)

    try:
        current_loop = asyncio.get_running_loop()
        current_loop.set_exception_handler(_loop_exception_handler)
    except RuntimeError:
        logger.info("Нет запущенного event loop для установки обработчика исключений.")

    logging.getLogger("pyrogram").setLevel(logging.INFO)

    # Регистрируем модульные хендлеры
    register_targets_handlers(dp)
    register_sender_handlers(dp)
    register_wizard_states_handlers(dp)
    register_main_handlers(
        dp=dp,
        bot=bot,
        user_id=USER_ID
    )

    # Запуск отправителя, если сессия уже существует
    bot_info = await bot.get_me()
    bot_id = bot_info.id
    await try_start_userbot_from_config(USER_ID, bot_id)

    # Запускаем фоновые задачи
    logger.info("Запуск фоновых задач...")
    asyncio.create_task(gift_purchase_worker(bot))
    asyncio.create_task(userbot_targets_updater(USER_ID))

    # Настройка стратегии повторных попыток подключения в случае ошибок
    # Используется для устойчивости к временным сбоям сети или сервера
    backoff_config = BackoffConfig(
        min_delay=1.0,
        max_delay=10.0,
        factor=2.0,
        jitter=0.2
    )

    logger.info("Бот готов к работе. Запуск polling...")
    await dp.start_polling(bot, backoff_config=backoff_config)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    try:
        asyncio.run(main())
    except Exception as main_exception:
        logger.critical(f"Критическая ошибка при запуске приложения: {main_exception}", exc_info=True)
        sys.exit(1)