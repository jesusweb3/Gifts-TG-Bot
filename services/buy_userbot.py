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
    logger.info("💳 ПОКУПКА: ========== НАЧАЛО ПРОЦЕССА ПОКУПКИ ПОДАРКА ==========")
    logger.info(f"💳 ПОКУПКА: Ссылка на подарок: {gift_link}")
    logger.info(f"💳 ПОКУПКА: Ожидаемая цена: ★{expected_price:,}")

    # Определяем получателя для логирования
    if target_user_id:
        recipient_display = f"User ID: {target_user_id}"
    elif target_chat_id:
        recipient_display = f"Chat: {target_chat_id}"
    else:
        recipient_display = "Не указан"
    logger.info(f"💳 ПОКУПКА: Получатель: {recipient_display}")

    # Проверяем баланс
    config = await get_valid_config()
    userbot_config = config.get("USERBOT", {})
    userbot_balance = userbot_config.get("BALANCE", 0)

    logger.debug(f"💰 ПОКУПКА: Проверка баланса - доступно: ★{userbot_balance:,}, требуется: ★{expected_price:,}")

    if userbot_balance < expected_price:
        logger.error(f"💸 ПОКУПКА: НЕДОСТАТОЧНО БАЛАНСА!")
        logger.error(f"💰 ПОКУПКА: Доступно: ★{userbot_balance:,}")
        logger.error(f"💸 ПОКУПКА: Требуется: ★{expected_price:,}")
        logger.error(f"📉 ПОКУПКА: Не хватает: ★{expected_price - userbot_balance:,}")

        # Отключаем отправитель из-за недостатка средств
        logger.warning("⚠️ ПОКУПКА: Отключение отправителя из-за недостатка баланса")
        config["USERBOT"]["ENABLED"] = False
        await save_config(config)

        return False

    logger.info("✅ ПОКУПКА: Баланс достаточен для покупки")

    # Получаем клиент отправителя
    client: Client = await get_userbot_client(session_user_id)
    if client is None:
        logger.error("❌ ПОКУПКА: Не удалось получить клиент отправителя")
        return False

    logger.debug("📤 ПОКУПКА: Клиент отправителя получен")

    # Определяем получателя для API
    recipient = target_user_id if target_user_id and not target_chat_id else (
        target_chat_id.lstrip('@') if target_chat_id and not target_user_id else None
    )

    if recipient is None:
        logger.error("❌ ПОКУПКА: Неверная конфигурация получателя - указаны оба параметра или ни одного")
        return False

    logger.debug(f"📥 ПОКУПКА: Получатель для API: {recipient}")

    # Попытки покупки
    for attempt in range(1, retries + 1):
        logger.info(f"🔄 ПОКУПКА: Попытка #{attempt}/{retries}")

        try:
            logger.debug("📞 ПОКУПКА: Вызов send_resold_gift")

            # Покупаем подарок с перепродажи
            result = await client.send_resold_gift(
                gift_link=gift_link,
                new_owner_chat_id=recipient,
                star_count=expected_price
            )

            if result:
                logger.info("🎉 ПОКУПКА: ПОКУПКА УСПЕШНА!")
                logger.info(f"📄 ПОКУПКА: Message ID: {result.id}")
                logger.info(f"📅 ПОКУПКА: Дата отправки: {result.date}")

                # Обновляем баланс в конфиге
                logger.debug(f"💰 ПОКУПКА: Списание ★{expected_price:,} с баланса")
                new_balance = await change_balance_userbot(-expected_price)

                logger.info(f"💰 ПОКУПКА: Новый баланс: ★{new_balance:,}")
                logger.info("✅ ПОКУПКА: ========== ПОКУПКА ЗАВЕРШЕНА УСПЕШНО ==========")

                return True
            else:
                logger.error("❌ ПОКУПКА: send_resold_gift вернул None - покупка не удалась")
                logger.error("❌ ПОКУПКА: ========== ПОКУПКА ЗАВЕРШЕНА С ОШИБКОЙ ==========")
                return False

        except FloodWait as e:
            logger.warning(f"⏳ ПОКУПКА: Flood wait - ожидание {e.value} секунд")
            logger.info(f"⏳ ПОКУПКА: Попытка #{attempt} приостановлена из-за ограничений Telegram")
            await asyncio.sleep(e.value)

        except BadRequest as e:
            error_msg = str(e)
            logger.error(f"❌ ПОКУПКА: BadRequest - {error_msg}")

            if "BALANCE_TOO_LOW" in error_msg or "not enough" in error_msg.lower():
                logger.error("💸 ПОКУПКА: Недостаточно звёзд на стороне Telegram")
                logger.error("❌ ПОКУПКА: ========== ПОКУПКА ЗАВЕРШЕНА С ОШИБКОЙ ==========")
                return False
            elif "GIFT_NOT_FOUND" in error_msg:
                logger.error("🎁 ПОКУПКА: Подарок не найден или уже куплен")
                logger.error("❌ ПОКУПКА: ========== ПОКУПКА ЗАВЕРШЕНА С ОШИБКОЙ ==========")
                return False
            elif "PRICE_CHANGED" in error_msg:
                logger.error("💰 ПОКУПКА: Цена подарка изменилась")
                logger.error("❌ ПОКУПКА: ========== ПОКУПКА ЗАВЕРШЕНА С ОШИБКОЙ ==========")
                return False
            else:
                logger.error(f"❌ ПОКУПКА: Критическая ошибка BadRequest: {e}")
                logger.error("❌ ПОКУПКА: ========== ПОКУПКА ЗАВЕРШЕНА С ОШИБКОЙ ==========")
                return False

        except Forbidden as e:
            logger.error(f"🚫 ПОКУПКА: Forbidden - доступ запрещен: {e}")
            logger.error("❌ ПОКУПКА: ========== ПОКУПКА ЗАВЕРШЕНА С ОШИБКОЙ ==========")
            return False

        except AuthKeyUnregistered as e:
            logger.error(f"🔑 ПОКУПКА: AuthKeyUnregistered - сессия недействительна: {e}")
            logger.error("❌ ПОКУПКА: ========== ПОКУПКА ЗАВЕРШЕНА С ОШИБКОЙ ==========")
            return False

        except RPCError as e:
            delay = 2 ** attempt
            logger.warning(f"⚠️ ПОКУПКА: RPC ошибка (попытка {attempt}): {e}")
            logger.info(f"⏳ ПОКУПКА: Повтор через {delay} секунд")
            await asyncio.sleep(delay)

        except Exception as e:
            delay = 2 ** attempt
            logger.error(f"💥 ПОКУПКА: Неожиданная ошибка (попытка {attempt}): {e}")
            if attempt < retries:
                logger.info(f"⏳ ПОКУПКА: Повтор через {delay} секунд")
                await asyncio.sleep(delay)

    logger.error(f"❌ ПОКУПКА: Не удалось купить подарок после {retries} попыток")
    logger.error(f"🔗 ПОКУПКА: Ссылка: {gift_link}")
    logger.error("❌ ПОКУПКА: ========== ПОКУПКА ЗАВЕРШЕНА С ОШИБКОЙ ==========")
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
    logger.debug("✅ ВАЛИДАЦИЯ: Начало валидации данных подарка")

    required_fields = ['link', 'price', 'name']

    # Проверяем наличие обязательных полей
    missing_fields = [field for field in required_fields if not gift_data.get(field)]
    if missing_fields:
        logger.error(f"❌ ВАЛИДАЦИЯ: Отсутствуют обязательные поля: {missing_fields}")
        return False

    # Проверяем цену
    gift_price = gift_data['price']
    if gift_price <= 0:
        logger.error(f"❌ ВАЛИДАЦИЯ: Некорректная цена подарка: {gift_price}")
        return False

    if gift_price > max_price:
        logger.error(f"❌ ВАЛИДАЦИЯ: Цена подарка (★{gift_price:,}) превышает лимит (★{max_price:,})")
        return False

    logger.debug(f"✅ ВАЛИДАЦИЯ: Цена подарка корректна: ★{gift_price:,} (лимит: ★{max_price:,})")

    # Проверяем получателя
    if not target_user_id and not target_chat_id:
        logger.error("❌ ВАЛИДАЦИЯ: Не указан получатель подарка")
        return False

    if target_user_id and target_chat_id:
        logger.error("❌ ВАЛИДАЦИЯ: Указаны оба получателя - user_id и chat_id")
        return False

    if target_user_id:
        logger.debug(f"✅ ВАЛИДАЦИЯ: Получатель - User ID: {target_user_id}")
    else:
        logger.debug(f"✅ ВАЛИДАЦИЯ: Получатель - Chat: {target_chat_id}")

    # Проверяем ссылку на подарок
    gift_link = gift_data['link']
    if not gift_link.startswith('https://t.me/nft/'):
        logger.error(f"❌ ВАЛИДАЦИЯ: Некорректная ссылка на подарок: {gift_link}")
        return False

    logger.debug(f"✅ ВАЛИДАЦИЯ: Ссылка на подарок корректна: {gift_link}")

    # Проверяем название подарка
    gift_name = gift_data['name']
    logger.debug(f"✅ ВАЛИДАЦИЯ: Название подарка: {gift_name}")

    logger.debug("✅ ВАЛИДАЦИЯ: Все проверки пройдены успешно")
    return True