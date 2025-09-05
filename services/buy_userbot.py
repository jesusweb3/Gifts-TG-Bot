# services/buy_userbot.py
"""
Модуль покупки подарков для перепродажи через Pyrogram отправитель.

Этот модуль содержит функции для:
- Покупки подарков с перепродажи через send_resold_gift.
- Обработки ошибок и повторных попыток при покупке.
- Валидации данных перед покупкой.

Основные функции:
- buy_resold_gift_userbot: Покупает подарок с перепродажи и отправляет получателю.
"""

# --- Стандартные библиотеки ---
import asyncio
import logging

# --- Внутренние модули ---
from services.config import get_valid_config, save_config
from services.balance import change_balance_userbot
from services.userbot import get_userbot_client

from pyrogram import Client
from pyrogram.errors import (
    FloodWait,
    BadRequest,
    Forbidden,
    RPCError,
    AuthKeyUnregistered
)

logger = logging.getLogger(__name__)


async def buy_resold_gift_userbot(
        session_user_id: int,
        gift_link: str,
        target_user_id: int | None,
        target_chat_id: str | None,
        expected_price: int,
        retries: int = 3
) -> bool:
    """
    Покупает подарок с перепродажи через Pyrogram отправитель.

    :param session_user_id: ID сессии отправителя
    :param gift_link: Ссылка на подарок (например: https://t.me/nft/SnoopDogg-13392)
    :param target_user_id: ID получателя-пользователя (или None)
    :param target_chat_id: Username получателя-канала (или None)
    :param expected_price: Ожидаемая стоимость подарка в звёздах
    :param retries: Количество попыток
    :return: True, если покупка успешна
    """
    config = await get_valid_config()
    userbot_config = config.get("USERBOT", {})
    userbot_balance = userbot_config.get("BALANCE", 0)

    if userbot_balance < expected_price:
        logger.error(
            f"Недостаточно звёзд для покупки подарка {gift_link} (требуется: {expected_price}, доступно: {userbot_balance})")

        config = await get_valid_config()
        config["USERBOT"]["ENABLED"] = False
        await save_config(config)

        return False

    client: Client = await get_userbot_client(session_user_id)
    if client is None:
        logger.error("Не удалось получить объект клиента отправителя.")
        return False

    # Определяем получателя
    recipient = target_user_id if target_user_id and not target_chat_id else (
        target_chat_id.lstrip('@') if target_chat_id and not target_user_id else None
    )

    if recipient is None:
        logger.warning("Указаны оба параметра — target_user_id и target_chat_id, или ни одного. Прерываем.")
        return False

    for attempt in range(1, retries + 1):
        try:
            logger.info(f"Попытка {attempt}/{retries} покупки подарка с перепродажи...")
            logger.info(f"Подарок: {gift_link}")
            logger.info(f"Получатель: {recipient}")
            logger.info(f"Ожидаемая цена: {expected_price} звезд")

            # Покупаем подарок с перепродажи
            result = await client.send_resold_gift(
                gift_link=gift_link,
                new_owner_chat_id=recipient,
                star_count=expected_price
            )

            if result:
                # Обновляем баланс в конфиге
                new_balance = await change_balance_userbot(-expected_price)

                logger.info(f"Успешная покупка подарка с перепродажи за {expected_price} звёзд. Остаток: {new_balance}")
                logger.info(f"Message ID: {result.id}, Дата: {result.date}")

                return True
            else:
                logger.error("send_resold_gift вернул None - покупка не удалась")
                return False

        except FloodWait as e:
            logger.error(f"Flood wait: ждём {e.value} секунд")
            await asyncio.sleep(e.value)

        except BadRequest as e:
            error_msg = str(e)
            if "BALANCE_TOO_LOW" in error_msg or "not enough" in error_msg.lower():
                logger.error(f"Недостаточно звёзд: {e}")
                return False
            elif "GIFT_NOT_FOUND" in error_msg:
                logger.error(f"Подарок не найден или уже куплен: {e}")
                return False
            elif "PRICE_CHANGED" in error_msg:
                logger.error(f"Цена подарка изменилась: {e}")
                return False
            else:
                logger.error(f"(BadRequest) Критическая ошибка: {e}")
                return False

        except Forbidden as e:
            logger.error(f"(Forbidden) Критическая ошибка: {e}")
            return False

        except AuthKeyUnregistered as e:
            logger.error(f"(AuthKeyUnregistered) Критическая ошибка: {e}")
            return False

        except RPCError as e:
            logger.error(f"RPC ошибка: {e}")
            await asyncio.sleep(2 ** attempt)

        except Exception as e:
            delay = 2 ** attempt
            logger.error(f"[{attempt}/{retries}] Ошибка отправителя при покупке: {e}. Повтор через {delay} сек...")
            await asyncio.sleep(delay)

    logger.error(f"Не удалось купить подарок {gift_link} после {retries} попыток.")
    return False


async def validate_gift_purchase(
        gift_data: dict,
        target_user_id: int | None,
        target_chat_id: str | None,
        max_price: int
) -> bool:
    """
    Валидирует данные перед покупкой подарка.

    :param gift_data: Данные подарка (должны содержать link, price, name)
    :param target_user_id: ID получателя
    :param target_chat_id: Username получателя
    :param max_price: Максимальная допустимая цена
    :return: True если данные валидны
    """
    required_fields = ['link', 'price', 'name']

    # Проверяем наличие обязательных полей
    for field in required_fields:
        if not gift_data.get(field):
            logger.error(f"Отсутствует обязательное поле: {field}")
            return False

    # Проверяем цену
    if gift_data['price'] <= 0:
        logger.error(f"Некорректная цена подарка: {gift_data['price']}")
        return False

    if gift_data['price'] > max_price:
        logger.error(f"Цена подарка ({gift_data['price']}) превышает лимит ({max_price})")
        return False

    # Проверяем получателя
    if not target_user_id and not target_chat_id:
        logger.error("Не указан получатель подарка")
        return False

    if target_user_id and target_chat_id:
        logger.error("Указаны оба получателя - user_id и chat_id")
        return False

    # Проверяем ссылку на подарок
    if not gift_data['link'].startswith('https://t.me/nft/'):
        logger.error(f"Некорректная ссылка на подарок: {gift_data['link']}")
        return False

    return True