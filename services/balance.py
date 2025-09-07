# services/balance.py
"""
Модуль работы с балансом звёзд отправителя.
Единственная точка для получения и управления балансом звезд в проекте.

Основные функции:
- get_sender_stars_balance: Получает актуальный баланс звёзд через Pyrogram сессию.
- refresh_balance: Обновляет баланс в конфиге и возвращает актуальное значение.
- change_balance_userbot: Изменяет баланс в конфиге (для учета трат).
"""

# --- Стандартные библиотеки ---
import logging
import asyncio

# --- Сторонние библиотеки ---
from pyrogram import Client
from pyrogram.errors import RPCError

# --- Внутренние модули ---
from services.config import load_config, save_config
from services.userbot import get_userbot_client, is_userbot_active

logger = logging.getLogger(__name__)


async def get_sender_stars_balance(user_id: int) -> float:
    """
    Получает актуальный баланс звёзд напрямую через Pyrogram сессию отправителя.
    Аналогично тестовому скрипту - прямой вызов get_stars_balance().

    :param user_id: ID пользователя (владельца конфига)
    :return: Баланс в звездах (float)
    :raises RuntimeError: Если отправитель неактивен или ошибка API
    """
    logger.debug(f"💰 БАЛАНС: Запрос актуального баланса звезд для пользователя {user_id}")

    # Проверяем что отправитель активен
    if not is_userbot_active(user_id):
        logger.error("❌ БАЛАНС: Отправитель неактивен")
        raise RuntimeError("Отправитель неактивен")

    # Получаем клиент отправителя
    client: Client = await get_userbot_client(user_id)
    if client is None:
        logger.error("❌ БАЛАНС: Не удалось получить клиент отправителя")
        raise RuntimeError("Не удалось получить клиент отправителя")

    # Проверяем что клиент запущен и авторизован
    if not client.is_connected:
        logger.error("❌ БАЛАНС: Клиент не подключен к Telegram")
        raise RuntimeError("Клиент не подключен к Telegram")

    try:
        logger.debug("📞 БАЛАНС: Прямой вызов get_stars_balance() через Pyrogram")

        # ПРЯМОЙ ВЫЗОВ как в тестовом скрипте
        balance = await client.get_stars_balance()

        logger.debug(f"📊 БАЛАНС: API ответ: {balance} (тип: {type(balance)})")

        # Проверяем тип данных и конвертируем
        if isinstance(balance, (int, float)):
            balance_float = float(balance)
            logger.info(f"✅ БАЛАНС: Получен актуальный баланс: {balance_float:,} ★")
            return balance_float
        else:
            logger.warning(f"⚠️ БАЛАНС: Неожиданный тип ответа: {type(balance)}, значение: {balance}")
            # Пытаемся привести к float
            try:
                balance_float = float(balance)
                logger.info(f"✅ БАЛАНС: Конвертирован баланс: {balance_float:,} ★")
                return balance_float
            except (ValueError, TypeError):
                logger.error(f"❌ БАЛАНС: Невозможно конвертировать {balance} в число")
                raise RuntimeError(f"Неожиданный формат баланса: {balance}")

    except RPCError as rpc_error:
        logger.error(f"❌ БАЛАНС: RPC ошибка Telegram API: {rpc_error}")
        raise RuntimeError(f"Ошибка Telegram API: {rpc_error}")
    except Exception as e:
        logger.error(f"❌ БАЛАНС: Критическая ошибка при получении баланса: {type(e).__name__}: {e}")

        # Дополнительная диагностика
        try:
            logger.debug("🔍 БАЛАНС: Проверка состояния сессии...")
            me = await client.get_me()
            logger.debug(f"✅ БАЛАНС: Сессия работает, авторизован как: {me.first_name}")
        except Exception as diag_error:
            logger.error(f"❌ БАЛАНС: Сессия также не работает: {diag_error}")

        raise RuntimeError(f"Ошибка получения баланса: {e}")


async def refresh_balance(user_id: int = None) -> int:
    """
    Обновляет баланс отправителя в конфиге, получая актуальные данные через Pyrogram.
    Единственная функция для обновления баланса в проекте.

    :param user_id: ID пользователя (опционально, берется из конфига если не указан)
    :return: Актуальный баланс звёзд (int)
    """
    logger.debug("💰 БАЛАНС: Начало обновления баланса в конфиге")

    config = await load_config()

    # Получаем user_id из конфига если не передан
    if user_id is None:
        user_id = config.get("USERBOT", {}).get("USER_ID")
        if not user_id:
            logger.debug("💰 БАЛАНС: USER_ID не найден в конфиге - отправитель не настроен")
            config["USERBOT"]["BALANCE"] = 0
            await save_config(config)
            return 0

    # Проверяем что отправитель настроен в конфиге
    userbot_data = config.get("USERBOT", {})
    has_session = bool(
        userbot_data.get("API_ID") and
        userbot_data.get("API_HASH") and
        userbot_data.get("PHONE")
    )

    if not has_session:
        logger.debug("💰 БАЛАНС: Отправитель не настроен в конфиге, баланс = 0")
        config["USERBOT"]["BALANCE"] = 0
        await save_config(config)
        return 0

    # Проверяем что отправитель активен
    if not is_userbot_active(user_id):
        logger.debug("💰 БАЛАНС: Отправитель неактивен, устанавливаем баланс в 0")
        config["USERBOT"]["BALANCE"] = 0
        await save_config(config)
        return 0

    # Получаем актуальный баланс через нашу основную функцию
    try:
        logger.debug("📞 БАЛАНС: Запрос актуального баланса через get_sender_stars_balance")

        balance_float = await get_sender_stars_balance(user_id)
        balance_int = int(balance_float)  # Конвертируем в int для конфига

        old_balance = config["USERBOT"].get("BALANCE", 0)
        config["USERBOT"]["BALANCE"] = balance_int

        if old_balance != balance_int:
            logger.info(f"💰 БАЛАНС: Баланс обновлен: {old_balance:,} ★ → {balance_int:,} ★")
        else:
            logger.debug(f"💰 БАЛАНС: Баланс не изменился: {balance_int:,} ★")

        await save_config(config)
        logger.debug(f"💰 БАЛАНС: Баланс сохранен в конфиг: {balance_int:,} ★")
        return balance_int

    except Exception as e:
        logger.error(f"❌ БАЛАНС: Не удалось получить актуальный баланс: {type(e).__name__}: {e}")

        # При ошибке устанавливаем баланс в 0
        config["USERBOT"]["BALANCE"] = 0
        await save_config(config)
        return 0


async def change_balance_userbot(delta: int, user_id: int = None) -> int:
    """
    Изменяет баланс звёзд отправителя в конфиге на delta.
    Используется для учета покупок/пополнений без запроса к API.

    :param delta: Изменение баланса (положительное = пополнение, отрицательное = трата)
    :param user_id: ID пользователя (опционально)
    :return: Новый баланс отправителя (int)
    """
    logger.debug(f"💰 БАЛАНС: Изменение баланса на {delta:+} ★")

    config = await load_config()
    userbot = config.get("USERBOT", {})
    current = userbot.get("BALANCE", 0)
    new_balance = max(0, current + delta)  # Не допускаем отрицательных значений

    config["USERBOT"]["BALANCE"] = new_balance
    await save_config(config)

    if delta > 0:
        logger.info(f"💰 БАЛАНС: Пополнение: {current:,} ★ + {delta:,} ★ = {new_balance:,} ★")
    elif delta < 0:
        actual_delta = new_balance - current  # Учитываем ограничение на минимум 0
        logger.info(f"💰 БАЛАНС: Списание: {current:,} ★ - {abs(actual_delta):,} ★ = {new_balance:,} ★")
        if actual_delta != delta:
            logger.warning(
                f"⚠️ БАЛАНС: Ограничение: попытка списать {abs(delta):,} ★, списано только {abs(actual_delta):,} ★")
    else:
        logger.debug(f"💰 БАЛАНС: Изменение на 0, баланс остался: {new_balance:,} ★")

    return new_balance


async def get_balance_from_config(user_id: int = None) -> int:
    """
    Получает баланс из конфига без запроса к API.
    Для быстрого получения кешированного значения.

    :param user_id: ID пользователя (опционально)
    :return: Баланс из конфига (int)
    """
    logger.debug("💰 БАЛАНС: Получение баланса из конфига (кеш)")

    config = await load_config()
    balance = config.get("USERBOT", {}).get("BALANCE", 0)

    logger.debug(f"💰 БАЛАНС: Кешированный баланс: {balance:,} ★")
    return balance


# Backward compatibility функции (если где-то используются старые названия)
async def get_sender_balance(user_id: int) -> int:
    """Устаревшая функция, используйте refresh_balance"""
    logger.warning("⚠️ БАЛАНС: Использование устаревшей функции get_sender_balance, используйте refresh_balance")
    return await refresh_balance(user_id)