# main.py
"""
Главный модуль приложения Telegram Gifts Bot (система таргетов) - единое сообщение.

Этот модуль содержит функции для:
- Запуска асинхронного приложения.
- Настройки и проверки конфигурации.
- Регистрации хендлеров.
- Управления фоновыми задачами (запуск/остановка по требованию).

Основные функции:
- main: Асинхронная точка входа в приложение.
- gift_purchase_worker: Фоновый воркер для покупки подарков по таргетам.
- start_workers: Запуск фоновых воркеров.
- stop_workers: Остановка фоновых воркеров.
- are_workers_running: Проверка состояния воркеров.
"""

# --- Стандартные библиотеки ---
import asyncio
import logging
import sys
from typing import Set, Optional

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
    logger.critical(
        "❌ КРИТИЧЕСКАЯ ОШИБКА: TELEGRAM_BOT_TOKEN и TELEGRAM_USER_ID должны быть заданы в переменных окружения")
    sys.exit(1)

# Глобальные переменные для управления воркерами
_running_tasks: Set[asyncio.Task] = set()
_bot_instance: Optional[Bot] = None


def are_workers_running() -> bool:
    """
    Проверяет, запущены ли фоновые воркеры.

    :return: True если воркеры запущены
    """
    return len(_running_tasks) > 0


async def stop_workers() -> None:
    """
    Останавливает все запущенные фоновые воркеры.
    """
    global _running_tasks

    if not _running_tasks:
        logger.info("🛑 ВОРКЕРЫ: Нет активных воркеров для остановки")
        return

    logger.info(f"🛑 ВОРКЕРЫ: Остановка {len(_running_tasks)} активных воркеров")

    # Отменяем все задачи
    for task in _running_tasks:
        if not task.done():
            task.cancel()
            logger.debug(f"🛑 ВОРКЕРЫ: Отменена задача: {task.get_name()}")

    # Ждем завершения всех задач
    if _running_tasks:
        await asyncio.gather(*_running_tasks, return_exceptions=True)

    _running_tasks.clear()
    logger.info("✅ ВОРКЕРЫ: Все воркеры успешно остановлены")


async def start_workers() -> bool:
    """
    Запускает фоновые воркеры если все условия выполнены.

    :return: True если воркеры запущены успешно
    """
    global _running_tasks, _bot_instance

    if not _bot_instance:
        logger.error("❌ ВОРКЕРЫ: Экземпляр бота не найден")
        return False

    # Проверяем условия для запуска
    config = await get_valid_config()

    # 1. Система должна быть активна
    if not config.get("ACTIVE", False):
        logger.warning("⚠️ ВОРКЕРЫ: Система неактивна - воркеры не будут запущены")
        return False

    # 2. Отправитель должен быть настроен и активен
    if not is_userbot_active(USER_ID):
        logger.warning("⚠️ ВОРКЕРЫ: Отправитель неактивен - воркеры не будут запущены")
        return False

    # 3. Получатель должен быть настроен
    target_user_id = config.get("TARGET_USER_ID")
    target_chat_id = config.get("TARGET_CHAT_ID")
    if not target_user_id and not target_chat_id:
        logger.warning("⚠️ ВОРКЕРЫ: Получатель не настроен - воркеры не будут запущены")
        return False

    # 4. Должен быть хотя бы один активный таргет
    targets = config.get("TARGETS", [])
    enabled_targets = [t for t in targets if t.get("ENABLED", True)]
    if not enabled_targets:
        logger.warning("⚠️ ВОРКЕРЫ: Нет активных таргетов - воркеры не будут запущены")
        return False

    # Останавливаем существующие воркеры если есть
    if _running_tasks:
        logger.info("🔄 ВОРКЕРЫ: Остановка существующих воркеров перед запуском новых")
        await stop_workers()

    logger.info("🚀 ВОРКЕРЫ: Все условия выполнены - запуск фоновых воркеров")

    # Запускаем воркеры
    logger.info("🛒 ВОРКЕРЫ: Запуск воркера покупки подарков")
    purchase_task = asyncio.create_task(gift_purchase_worker(_bot_instance), name="gift_purchase_worker")
    _running_tasks.add(purchase_task)

    logger.info("🎯 ВОРКЕРЫ: Запуск воркера обновления таргетов")
    targets_task = asyncio.create_task(userbot_targets_updater(USER_ID), name="userbot_targets_updater")
    _running_tasks.add(targets_task)

    # Добавляем callback для очистки завершенных задач
    def task_done_callback(task: asyncio.Task):
        _running_tasks.discard(task)
        if task.cancelled():
            logger.debug(f"🛑 ВОРКЕРЫ: Задача отменена: {task.get_name()}")
        elif task.exception():
            logger.error(f"💥 ВОРКЕРЫ: Задача завершилась с ошибкой: {task.get_name()}: {task.exception()}")
        else:
            logger.info(f"✅ ВОРКЕРЫ: Задача завершена: {task.get_name()}")

    purchase_task.add_done_callback(task_done_callback)
    targets_task.add_done_callback(task_done_callback)

    logger.info(f"✅ ВОРКЕРЫ: Запущено {len(_running_tasks)} фоновых воркеров")
    logger.info(f"🎯 ВОРКЕРЫ: Активных таргетов: {len(enabled_targets)}")

    return True


async def gift_purchase_worker(bot: Bot) -> None:
    """
    Фоновый воркер для покупки подарков по системе таргетов.
    Мониторит доступные подарки по каждому таргету и покупает те, которые соответствуют условиям.
    Использует единое сообщение для уведомлений.

    :param bot: Экземпляр бота aiogram
    :return: None
    """
    logger.info("🔄 ВОРКЕР ПОКУПОК: Запуск воркера покупки подарков по таргетам")

    # Инициализация баланса
    logger.debug("🔄 ВОРКЕР ПОКУПОК: Инициализация баланса отправителя")
    await refresh_balance()

    cycle_count = 0
    logger.info("🟢 ВОРКЕР ПОКУПОК: Воркер успешно запущен и готов к работе")

    try:
        while True:
            cycle_count += 1

            try:
                # Загружаем конфигурацию
                config = await get_valid_config()

                # Проверяем активность системы
                if not config["ACTIVE"]:
                    logger.info("⏸️ ВОРКЕР ПОКУПОК: Система деактивирована - завершение работы воркера")
                    break

                logger.debug(f"🔄 ВОРКЕР ПОКУПОК: Цикл #{cycle_count} - система активна, начинаем проверки")

                # Проверяем что отправитель активен
                if not is_userbot_active(USER_ID):
                    logger.warning("⚠️ ВОРКЕР ПОКУПОК: Отправитель неактивен - останавливаем систему")
                    config["ACTIVE"] = False
                    await save_config(config)

                    text = ("⚠️ <b>Отправитель неактивен</b>\n\n"
                            "📤 Настройте отправитель для продолжения работы!\n"
                            "🚦 Статус изменён на 🔴 (неактивен).")

                    logger.info("📤 ВОРКЕР ПОКУПОК: Отправка уведомления о неактивном отправителе")
                    await bot.send_message(chat_id=USER_ID, text=text)
                    await send_main_menu(bot=bot, chat_id=USER_ID, user_id=USER_ID)
                    break

                # Получаем конфигурацию таргетов и получателя
                target_user_id = config.get("TARGET_USER_ID")
                target_chat_id = config.get("TARGET_CHAT_ID")
                targets = config.get("TARGETS", [])
                enabled_targets = [t for t in targets if t.get("ENABLED", True)]

                if not enabled_targets:
                    if cycle_count % 60 == 0:  # Логируем каждую минуту
                        logger.debug("📋 ВОРКЕР ПОКУПОК: Нет активных таргетов для мониторинга")
                    await asyncio.sleep(DEFAULT_BOT_DELAY)
                    continue

                # Проверяем получателя
                if not target_user_id and not target_chat_id:
                    logger.warning("⚠️ ВОРКЕР ПОКУПОК: Получатель не настроен - останавливаем систему")
                    config["ACTIVE"] = False
                    await save_config(config)

                    text = ("⚠️ <b>Получатель не настроен</b>\n\n"
                            "📥 Настройте получателя для продолжения работы!\n"
                            "🚦 Статус изменён на 🔴 (неактивен).")

                    logger.info("📥 ВОРКЕР ПОКУПОК: Отправка уведомления о неустановленном получателе")
                    await bot.send_message(chat_id=USER_ID, text=text)
                    await send_main_menu(bot=bot, chat_id=USER_ID, user_id=USER_ID)
                    break

                # Получаем список всех доступных подарков для таргетов из кеша
                available_target_gifts = get_all_available_target_gifts(USER_ID)

                if cycle_count % 20 == 0:  # Логируем каждые 20 секунд
                    logger.debug(
                        f"📦 ВОРКЕР ПОКУПОК: Доступно подарков: {len(available_target_gifts)}, активных таргетов: {len(enabled_targets)}")

                if not available_target_gifts:
                    if cycle_count % 60 == 0:  # Логируем каждую минуту
                        logger.debug("📦 ВОРКЕР ПОКУПОК: Нет доступных подарков по таргетам в кеше")
                    await asyncio.sleep(DEFAULT_BOT_DELAY)
                    continue

                purchased_any = False

                logger.debug(f"🔍 ВОРКЕР ПОКУПОК: Анализ {len(available_target_gifts)} доступных подарков")

                # Проверяем каждый доступный подарок для таргетов
                for gift_index, target_gift in enumerate(available_target_gifts, 1):
                    target_index = target_gift.get("target_index")
                    target_gift_name = target_gift.get("target_gift_name", "🎁")
                    target_max_price = target_gift.get("target_max_price", 0)
                    gift_price = target_gift.get("price", 0)
                    gift_link = target_gift.get("link", "")
                    gift_name = target_gift.get("name", "Unknown")

                    logger.debug(
                        f"🎁 ВОРКЕР ПОКУПОК: Проверка подарка {gift_index}/{len(available_target_gifts)} - {gift_name} за ★{gift_price:,}")

                    if not gift_link:
                        logger.warning(f"⚠️ ВОРКЕР ПОКУПОК: У подарка таргета {target_index} отсутствует ссылка")
                        continue

                    # Проверяем что цена в пределах лимита (дополнительная проверка)
                    if gift_price > target_max_price:
                        logger.warning(
                            f"💰 ВОРКЕР ПОКУПОК: Цена подарка {gift_price} превышает лимит таргета {target_max_price}")
                        continue

                    # Валидируем данные перед покупкой
                    logger.debug(f"✅ ВОРКЕР ПОКУПОК: Валидация данных подарка для таргета {target_index}")
                    if not await validate_gift_purchase(
                            gift_data=target_gift,
                            target_user_id=target_user_id,
                            target_chat_id=target_chat_id,
                            max_price=target_max_price
                    ):
                        logger.warning(f"❌ ВОРКЕР ПОКУПОК: Валидация не прошла для подарка таргета {target_index}")
                        continue

                    # Пытаемся купить подарок
                    logger.info(f"🎯 ВОРКЕР ПОКУПОК: НАЙДЕН ПОДХОДЯЩИЙ ПОДАРОК!")
                    logger.info(f"🎯 ВОРКЕР ПОКУПОК: Таргет: {target_gift_name} (#{target_index})")
                    logger.info(
                        f"🎁 ВОРКЕР ПОКУПОК: Подарок: {gift_name} за ★{gift_price:,} (лимит ★{target_max_price:,})")
                    logger.info(f"🔗 ВОРКЕР ПОКУПОК: Ссылка: {gift_link}")

                    logger.info("💳 ВОРКЕР ПОКУПОК: Начинаем процесс покупки...")
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

                        logger.info("🎉 ВОРКЕР ПОКУПОК: ПОКУПКА УСПЕШНА!")
                        logger.info(f"🎯 ВОРКЕР ПОКУПОК: Таргет: {target_gift_name}")
                        logger.info(f"🎁 ВОРКЕР ПОКУПОК: Подарок: {gift_name} за ★{gift_price:,}")
                        logger.info(f"📤 ВОРКЕР ПОКУПОК: Отправитель: {sender_name}")
                        logger.info(f"📥 ВОРКЕР ПОКУПОК: Получатель: {target_display}")

                        text = (f"✅ <b>Подарок отправлен!</b>\n\n"
                                f"🎯 Таргет: {target_gift_name}\n"
                                f"🎁 Подарок: {gift_name} за ★{gift_price:,}\n"
                                f"💰 Лимит: ★{target_max_price:,}\n"
                                f"📤 Отправитель: {sender_name}\n"
                                f"📥 Получатель: {target_display}\n"
                                f"🔗 Ссылка: {gift_link}")

                        # Отправляем уведомление об успешной покупке
                        logger.info("📲 ВОРКЕР ПОКУПОК: Отправка уведомления пользователю об успешной покупке")
                        await bot.send_message(chat_id=USER_ID, text=text)
                        await send_main_menu(bot=bot, chat_id=USER_ID, user_id=USER_ID)

                        logger.info("🔄 ВОРКЕР ПОКУПОК: Обновление баланса после покупки")
                        await refresh_balance()
                        purchased_any = True

                        # Делаем паузу между покупками
                        logger.info(f"⏳ ВОРКЕР ПОКУПОК: Пауза {PURCHASE_COOLDOWN} сек между покупками")
                        await asyncio.sleep(PURCHASE_COOLDOWN)

                        # Прерываем цикл после успешной покупки, чтобы обновить данные
                        logger.debug("🔄 ВОРКЕР ПОКУПОК: Прерывание цикла для обновления данных")
                        break
                    else:
                        logger.error(
                            f"❌ ВОРКЕР ПОКУПОК: Не удалось купить подарок для таргета {target_index}: {gift_name}")

                # Если ни один подарок не удалось купить, возможно проблема с балансом или доступом
                if not purchased_any and available_target_gifts:
                    # Проверяем баланс
                    logger.debug("💰 ВОРКЕР ПОКУПОК: Проверка баланса после неудачных попыток покупки")
                    current_balance = await refresh_balance()
                    min_price = min(gift.get("price", 0) for gift in available_target_gifts)

                    if current_balance < min_price:
                        logger.error(f"💸 ВОРКЕР ПОКУПОК: НЕДОСТАТОЧНО БАЛАНСА!")
                        logger.error(f"💰 ВОРКЕР ПОКУПОК: Текущий баланс: {current_balance} ★")
                        logger.error(f"💸 ВОРКЕР ПОКУПОК: Требуется минимум: {min_price} ★")

                        config["ACTIVE"] = False
                        await save_config(config)

                        text = (f"⚠️ <b>Недостаточно звезд</b>\n\n"
                                f"💰 Баланс: {current_balance} ★\n"
                                f"💸 Требуется минимум: {min_price} ★\n"
                                f"🚦 Статус изменён на 🔴 (неактивен).")

                        logger.info("📲 ВОРКЕР ПОКУПОК: Отправка уведомления о недостатке баланса")
                        await bot.send_message(chat_id=USER_ID, text=text)
                        await send_main_menu(bot=bot, chat_id=USER_ID, user_id=USER_ID)
                        break
                    else:
                        if cycle_count % 30 == 0:  # Логируем каждые 30 секунд
                            logger.debug(
                                "📦 ВОРКЕР ПОКУПОК: Доступные подарки есть, но покупка не удалась (возможно, уже куплены)")

            except Exception as e:
                logger.error(f"💥 ВОРКЕР ПОКУПОК: Критическая ошибка в цикле: {e}", exc_info=True)

            await asyncio.sleep(DEFAULT_BOT_DELAY)

    except asyncio.CancelledError:
        logger.info("🛑 ВОРКЕР ПОКУПОК: Воркер остановлен по запросу")
        raise
    except Exception as e:
        logger.error(f"💥 ВОРКЕР ПОКУПОК: Критическая ошибка воркера: {e}", exc_info=True)
    finally:
        logger.info("🏁 ВОРКЕР ПОКУПОК: Завершение работы воркера покупки подарков")


async def main() -> None:
    """
    Асинхронная точка входа в приложение (система таргетов) - единое сообщение.

    - Проверяет конфигурационный файл (config.json)
    - Создаёт HTTP-сессию и объект бота
    - Регистрирует хендлеры
    - Запускает отправитель (если он настроен)
    - НЕ запускает фоновые задачи автоматически - они запускаются только при активации системы

    :return: None
    """
    global _bot_instance

    logger.info("=" * 80)
    logger.info(f"🚀 STARTUP: Telegram Gifts Bot v{VERSION} - ЗАПУСК ПРИЛОЖЕНИЯ")
    logger.info("=" * 80)

    # Проверяем наличие параметра CONFIG_DATA
    env_config_data = get_env_variable("CONFIG_DATA", None)
    if env_config_data is not None:
        await update_config_from_env(config_data=env_config_data)

    # Проверяем конфигурацию
    await ensure_config()
    logger.info("✅ STARTUP: Конфигурация готова")

    # Создаем бота
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    _bot_instance = bot  # Сохраняем ссылку для воркеров
    logger.info("✅ STARTUP: Экземпляр бота создан")

    # Получаем информацию о боте
    try:
        bot_info = await bot.get_me()
    except Exception as e:
        logger.error(f"❌ STARTUP: Ошибка подключения к боту: {e}")
        sys.exit(1)

    # Простая защита: отключение громоздких traceback'ов SecurityCheckMismatch
    def _loop_exception_handler(event_loop, context):
        exception = context.get("exception")
        if isinstance(exception, SecurityCheckMismatch):
            return
        event_loop.default_exception_handler(context)

    try:
        current_loop = asyncio.get_running_loop()
        current_loop.set_exception_handler(_loop_exception_handler)
    except RuntimeError:
        pass

    # Настройка логирования для сторонних библиотек
    logging.getLogger("pyrogram").setLevel(logging.CRITICAL)
    logging.getLogger("aiogram.dispatcher").setLevel(logging.WARNING)
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)

    # Регистрируем модульные хендлеры
    register_targets_handlers(dp)
    register_sender_handlers(dp)
    register_wizard_states_handlers(dp)
    register_main_handlers(dp=dp, bot=bot, user_id=USER_ID)
    logger.info("✅ STARTUP: Все обработчики событий зарегистрированы")

    # Запуск отправителя, если сессия уже существует
    bot_id = bot_info.id
    userbot_started = await try_start_userbot_from_config(USER_ID, bot_id)

    # Настройка стратегии повторных попыток подключения в случае ошибок
    backoff_config = BackoffConfig(
        min_delay=1.0,
        max_delay=10.0,
        factor=2.0,
        jitter=0.2
    )

    logger.info("🔄 STARTUP: Запуск polling для обработки событий Telegram")
    logger.info("🟢 STARTUP: ИНИЦИАЛИЗАЦИЯ ЗАВЕРШЕНА - БОТ ГОТОВ К РАБОТЕ")
    logger.info("=" * 80)

    try:
        await dp.start_polling(bot, backoff_config=backoff_config)
    finally:
        # Останавливаем воркеры при завершении
        await stop_workers()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 SHUTDOWN: Получен сигнал завершения (Ctrl+C)")
        logger.info("👋 SHUTDOWN: Telegram Gifts Bot остановлен пользователем")
    except Exception as main_exception:
        logger.critical(f"💥 CRITICAL: Критическая ошибка при запуске приложения: {main_exception}", exc_info=True)
        sys.exit(1)