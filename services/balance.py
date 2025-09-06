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
from services.userbot import get_userbot_stars_balance, is_userbot_active

logger = logging.getLogger(__name__)


async def refresh_balance() -> int:
    """
    Обновляет баланс отправителя в конфиге и возвращает актуальное значение.
    :return: Баланс звёзд отправителя (int)
    """
    logger.debug("💰 БАЛАНС: Начало обновления баланса отправителя")

    config = await load_config()
    userbot_data = config.get("USERBOT", {})

    # Проверяем наличие сессии отправителя
    has_session = bool(
        userbot_data.get("API_ID") and
        userbot_data.get("API_HASH") and
        userbot_data.get("PHONE")
    )

    if has_session:
        logger.debug("💰 БАЛАНС: Сессия отправителя найдена, получение баланса")

        # Дополнительная проверка активности
        user_id = userbot_data.get("USER_ID")
        if user_id and is_userbot_active(user_id):
            try:
                userbot_balance = await get_userbot_balance()
                old_balance = config["USERBOT"].get("BALANCE", 0)
                config["USERBOT"]["BALANCE"] = userbot_balance

                if old_balance != userbot_balance:
                    logger.info(f"💰 БАЛАНС: Баланс обновлен: {old_balance} ★ → {userbot_balance:,} ★")
                else:
                    logger.debug(f"💰 БАЛАНС: Баланс не изменился: {userbot_balance:,} ★")

            except Exception as e:
                config["USERBOT"]["BALANCE"] = 0
                logger.error(f"❌ БАЛАНС: Ошибка получения баланса отправителя: {e}")
        else:
            logger.debug("💰 БАЛАНС: Отправитель неактивен, устанавливаем баланс в 0")
            config["USERBOT"]["BALANCE"] = 0
    else:
        logger.debug("💰 БАЛАНС: Сессия отправителя не настроена, баланс = 0")
        config["USERBOT"]["BALANCE"] = 0

    await save_config(config)
    final_balance = config["USERBOT"]["BALANCE"]

    logger.debug(f"💰 БАЛАНС: Итоговый баланс в конфиге: {final_balance:,} ★")
    return final_balance


async def change_balance_userbot(delta: int) -> int:
    """
    Изменяет баланс звёзд отправителя в конфиге на delta, не допуская отрицательных значений.
    :param delta: Изменение баланса (int)
    :return: Новый баланс отправителя (int)
    """
    logger.debug(f"💰 БАЛАНС: Изменение баланса на {delta:+} ★")

    config = await load_config()
    userbot = config.get("USERBOT", {})
    current = userbot.get("BALANCE", 0)
    new_balance = max(0, current + delta)

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


async def get_userbot_balance() -> int:
    """
    Получает баланс звёзд у отправитель-сессии.
    :return: Баланс отправителя (int)
    """
    logger.debug("💰 БАЛАНС: Запрос баланса у отправитель-сессии")

    try:
        balance = await get_userbot_stars_balance()
        logger.debug(f"💰 БАЛАНС: Получен баланс от отправителя: {balance:,} ★")
        return balance
    except Exception as e:
        logger.error(f"❌ БАЛАНС: Ошибка при получении баланса от отправителя: {e}")
        raise