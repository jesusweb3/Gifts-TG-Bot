# services/buy_userbot.py
"""
Модуль покупки подарков для перепродажи через Pyrogram отправитель.

Этот модуль содержит функции для:
- Покупки подарков с перепродажи через send_resold_gift.
- Обработки ошибок и повторных попыток при покупке.
- Валидации данных перед покупкой.
- ИСПРАВЛЕНО: Правильное использование модуля баланса.

Основные функции:
- buy_resold_gift_userbot: Покупает подарок с перепродажи и отправляет получателю.
"""

# --- Стандартные библиотеки ---
import asyncio
import logging

# --- Внутренние модули ---
from services.config import get_valid_config, save_config
from services.balance import get_sender_stars_balance, change_balance_userbot  # ИСПРАВЛЕНО: Используем правильный модуль баланса
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
    ИСПРАВЛЕНО: Правильное использование модуля баланса для проверки и обновления.

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

    # ИСПРАВЛЕНО: Проверяем баланс через правильный модуль (предварительная проверка)
    config = await get_valid_config()
    userbot_config = config.get("USERBOT", {})
    cached_balance = userbot_config.get("BALANCE", 0)

    logger.debug(f"💰 ПОКУПКА: Предварительная проверка - кешированный баланс: ★{cached_balance:,}, требуется: ★{expected_price:,}")

    if cached_balance < expected_price:
        logger.error(f"💸 ПОКУПКА: НЕДОСТАТОЧНО БАЛАНСА (по кешу)!")
        logger.error(f"💰 ПОКУПКА: Кешированный баланс: ★{cached_balance:,}")
        logger.error(f"💸 ПОКУПКА: Требуется: ★{expected_price:,}")

        # Отключаем отправитель из-за недостатка средств
        logger.warning("⚠️ ПОКУПКА: Отключение отправителя из-за недостатка баланса")
        config["USERBOT"]["ENABLED"] = False
        await save_config(config)

        return False

    logger.info("✅ ПОКУПКА: Предварительная проверка баланса пройдена")

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

    # ИСПРАВЛЕНО: Получаем актуальный баланс через правильный модуль
    try:
        balance_before_float = await get_sender_stars_balance(session_user_id)
        balance_before = int(balance_before_float)  # Конвертируем в int для сравнения
        logger.info(f"💰 ПОКУПКА: Актуальный баланс ДО покупки: ★{balance_before:,}")
    except Exception as balance_error:
        logger.error(f"❌ ПОКУПКА: Не удалось получить актуальный баланс: {balance_error}")
        return False

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

            # send_resold_gift может вернуть None при успехе
            # Проверяем успех по изменению баланса
            logger.info("🔍 ПОКУПКА: Проверка успеха покупки через баланс...")

            # Небольшая пауза для обновления баланса на серверах Telegram
            await asyncio.sleep(1.0)

            # ИСПРАВЛЕНО: Получаем актуальный баланс через правильный модуль
            try:
                balance_after_float = await get_sender_stars_balance(session_user_id)
                balance_after = int(balance_after_float)  # Конвертируем в int для сравнения
            except Exception as balance_error:
                logger.error(f"❌ ПОКУПКА: Не удалось получить баланс после покупки: {balance_error}")
                continue  # Переходим к следующей попытке

            logger.info(f"💰 ПОКУПКА: Баланс ПОСЛЕ покупки: ★{balance_after:,}")

            balance_diff = balance_before - balance_after
            logger.info(f"💸 ПОКУПКА: Разница в балансе: ★{balance_diff:,}")

            # Проверяем что баланс уменьшился на ожидаемую сумму (с небольшой погрешностью)
            if abs(balance_diff - expected_price) <= 1:  # Погрешность ±1 звезда
                logger.info("🎉 ПОКУПКА: ПОКУПКА УСПЕШНА!")
                logger.info(f"💰 ПОКУПКА: Списано со счета: ★{balance_diff:,}")
                logger.info(f"💰 ПОКУПКА: Ожидалось списать: ★{expected_price:,}")

                if result:
                    logger.info(f"📄 ПОКУПКА: Message ID: {result.id}")
                    logger.info(f"📅 ПОКУПКА: Дата отправки: {result.date}")
                else:
                    logger.info("📄 ПОКУПКА: API вернул None (нормально для некоторых версий)")

                # ИСПРАВЛЕНО: Обновляем баланс в конфиге через правильный модуль
                logger.debug(f"💰 ПОКУПКА: Обновление баланса в конфиге: ★{balance_after:,}")
                delta = balance_after - cached_balance  # Вычисляем изменение от предыдущего значения
                await change_balance_userbot(delta, session_user_id)

                logger.info("✅ ПОКУПКА: ========== ПОКУПКА ЗАВЕРШЕНА УСПЕШНО ==========")
                return True
            elif balance_diff > 0:
                # Баланс уменьшился, но не на ожидаемую сумму
                logger.warning(f"⚠️ ПОКУПКА: Баланс изменился неожиданно!")
                logger.warning(f"💰 ПОКУПКА: Ожидалось списать: ★{expected_price:,}")
                logger.warning(f"💸 ПОКУПКА: Реально списалось: ★{balance_diff:,}")

                # Все равно считаем это успехом, так как деньги списались
                logger.info("🎉 ПОКУПКА: ПОКУПКА ВЕРОЯТНО УСПЕШНА (нестандартная цена)")

                # ИСПРАВЛЕНО: Обновляем баланс в конфиге через правильный модуль
                delta = balance_after - cached_balance
                await change_balance_userbot(delta, session_user_id)

                logger.info("✅ ПОКУПКА: ========== ПОКУПКА ЗАВЕРШЕНА УСПЕШНО ==========")
                return True
            else:
                # Баланс не изменился - покупка не прошла
                logger.error("❌ ПОКУПКА: Баланс не изменился - покупка не удалась")
                logger.error(f"💰 ПОКУПКА: Баланс до: ★{balance_before:,}")
                logger.error(f"💰 ПОКУПКА: Баланс после: ★{balance_after:,}")

                # Продолжаем к следующей попытке
                continue

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