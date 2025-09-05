# services/balance.py
"""
Модуль работы с балансом звёзд отправителя.

Этот модуль содержит функции для:
- Получения текущего баланса звёзд через отправитель.
- Обновления баланса звёзд в конфиге.
- Изменения баланса звёзд с учётом ограничений.

Основные функции:
- refresh_balance: Обновляет баланс отправителя в конфиге.
- change_balance_userbot: Изменяет баланс звёзд отправителя в конфиге.
- get_userbot_balance: Получает баланс звёзд у отправитель-сессии.
"""

# --- Стандартные библиотеки ---
import logging

# --- Внутренние модули ---
from services.config import load_config, save_config
from services.userbot import get_userbot_stars_balance

logger = logging.getLogger(__name__)


async def refresh_balance() -> int:
    """
    Обновляет баланс отправителя в конфиге и возвращает актуальное значение.
    :return: Баланс звёзд отправителя (int)
    """
    config = await load_config()
    userbot_data = config.get("USERBOT", {})

    # Баланс отправителя (если сессия существует)
    has_session = bool(
        userbot_data.get("API_ID") and
        userbot_data.get("API_HASH") and
        userbot_data.get("PHONE")
    )

    if has_session:
        try:
            userbot_balance = await get_userbot_balance()
            config["USERBOT"]["BALANCE"] = userbot_balance
        except Exception as e:
            config["USERBOT"]["BALANCE"] = 0
            logger.error(f"Не удалось получить баланс отправителя: {e}")
    else:
        logger.info("Отправитель-сессия неактивна или не настроена.")
        config["USERBOT"]["BALANCE"] = 0

    await save_config(config)
    return config["USERBOT"]["BALANCE"]


async def change_balance_userbot(delta: int) -> int:
    """
    Изменяет баланс звёзд отправителя в конфиге на delta, не допуская отрицательных значений.
    :param delta: Изменение баланса (int)
    :return: Новый баланс отправителя (int)
    """
    config = await load_config()
    userbot = config.get("USERBOT", {})
    current = userbot.get("BALANCE", 0)
    new_balance = max(0, current + delta)

    config["USERBOT"]["BALANCE"] = new_balance
    await save_config(config)
    return new_balance


async def get_userbot_balance() -> int:
    """
    Получает баланс звёзд у отправитель-сессии.
    :return: Баланс отправителя (int)
    """
    return await get_userbot_stars_balance()