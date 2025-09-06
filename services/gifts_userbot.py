# services/gifts_userbot.py
"""
Модуль работы с подарками для перепродажи через Pyrogram отправитель.

Этот модуль содержит функции для:
- Получения списка подарков доступных для перепродажи.
- Поиска самого дешевого подарка по ID за звезды (не TON).
- Нормализации данных подарков.

Основные функции:
- get_available_resale_gifts: Получает все подарки доступные для перепродажи.
- find_cheapest_gift_by_id: Находит самый дешевый подарок по ID за звезды.
- normalize_resale_gift: Преобразует объект подарка в словарь.
- check_gift_availability: Простая проверка существования подарка (без поиска цен).
"""

# --- Стандартные библиотеки ---
import logging

# --- Сторонние библиотеки ---
from pyrogram import Client, enums
from pyrogram.types import Gift

# --- Внутренние модули ---
from services.config import MORE_LOGS, get_valid_config
from services.userbot import get_userbot_client, is_userbot_active

logger = logging.getLogger(__name__)


def normalize_resale_gift(gift) -> dict:
    """
    Преобразует объект подарка для перепродажи в словарь с ключевыми характеристиками.

    :param gift: Объект подарка для перепродажи из Pyrogram
    :return: Словарь с параметрами подарка
    """
    star_price = getattr(gift, 'last_resale_star_count', None)
    collectible_id = getattr(gift, 'collectible_id', 'Unknown')
    name = getattr(gift, 'name', 'Unknown')
    link = getattr(gift, 'link', '')

    # Проверяем resale_ton_only
    resale_ton_only = False
    try:
        if hasattr(gift, 'raw') and hasattr(gift.raw, 'resale_ton_only'):
            resale_ton_only = gift.raw.resale_ton_only
    except AttributeError:
        pass

    # Извлекаем атрибуты
    attributes = []
    if hasattr(gift, 'attributes') and gift.attributes:
        attributes = [attr.name for attr in gift.attributes if hasattr(attr, 'name')]

    result = {
        "id": collectible_id,
        "gift_id": getattr(gift, 'gift_id', None),
        "price": star_price or 0,
        "name": name,
        "link": link,
        "attributes": attributes,
        "resale_ton_only": resale_ton_only,
        "available_for_stars": star_price is not None and not resale_ton_only
    }

    logger.debug(
        f"🔄 НОРМАЛИЗАЦИЯ: Подарок {name} - цена: ★{star_price or 0}, доступен за звезды: {result['available_for_stars']}")

    return result


async def get_available_resale_gifts(user_id: int) -> list[dict]:
    """
    Получает список всех подарков доступных для перепродажи.

    :param user_id: Telegram ID владельца отправитель-сессии
    :return: Список словарей с доступными подарками для перепродажи
    """
    logger.debug(f"🎁 ПОДАРКИ: Запрос списка подарков для перепродажи (пользователь {user_id})")

    if not is_userbot_active(user_id):
        logger.debug("📤 ПОДАРКИ: Отправитель неактивен - возвращаем пустой список")
        return []

    try:
        config = await get_valid_config()
        userbot_config = config.get("USERBOT", {})
        if not userbot_config.get("ENABLED", False):
            logger.debug("📤 ПОДАРКИ: Отправитель отключен в конфиге - возвращаем пустой список")
            return []

        client: Client = await get_userbot_client(user_id)
        if client is None:
            logger.error("❌ ПОДАРКИ: Не удалось получить клиент отправителя")
            return []

        logger.debug("📞 ПОДАРКИ: Запрос базовых подарков через get_available_gifts")

        # Получаем подарки доступные для покупки
        available_gifts: list[Gift] = await client.get_available_gifts()

        logger.info(f"📦 ПОДАРКИ: Получено {len(available_gifts)} базовых типов подарков")

        # Фильтруем только те, которые доступны для перепродажи
        resale_gifts = []
        for gift in available_gifts:
            gift_id = getattr(gift, 'id', 'Unknown')
            title = getattr(gift, 'title', 'No Title')
            resale_amount = getattr(gift, 'available_resale_amount', 0)

            # Обрабатываем None значения
            if title is None:
                title = 'No Title'

            # Только подарки которые есть на перепродаже
            if resale_amount and resale_amount > 0:
                resale_gifts.append({
                    'id': gift_id,
                    'title': title,
                    'resale_amount': resale_amount
                })

                if MORE_LOGS:
                    logger.debug(
                        f"✅ ПОДАРКИ: Доступен для перепродажи - {title} (ID: {gift_id}, количество: {resale_amount})")

        logger.info(f"🎯 ПОДАРКИ: Найдено {len(resale_gifts)} типов подарков доступных для перепродажи")

        if resale_gifts:
            total_amount = sum(gift['resale_amount'] for gift in resale_gifts)
            logger.info(f"📊 ПОДАРКИ: Общее количество подарков для перепродажи: {total_amount:,}")

        return resale_gifts

    except Exception as e:
        logger.error(f"💥 ПОДАРКИ: Ошибка получения подарков для перепродажи: {e}")
        return []


async def find_cheapest_gift_by_id(user_id: int, gift_id: int, max_price: int = None,
                                   max_check: int = None) -> dict | None:
    """
    Находит самый дешевый подарок по ID за звезды (не TON).
    Ищет до первого найденного подарка за звезды (самый дешевый).

    :param user_id: Telegram ID владельца отправитель-сессии
    :param gift_id: ID типа подарка для поиска
    :param max_price: Максимальная цена в звездах (если None - без ограничений)
    :param max_check: НЕ ИСПОЛЬЗУЕТСЯ - для совместимости
    :return: Словарь с данными подарка или None если не найден
    """
    logger.info(f"🔍 ПОИСК: Поиск самого дешевого подарка ID {gift_id} за звезды")
    if max_price:
        logger.info(f"💰 ПОИСК: Ценовой лимит: ★{max_price:,}")

    if not is_userbot_active(user_id):
        logger.debug("📤 ПОИСК: Отправитель неактивен - поиск невозможен")
        return None

    try:
        config = await get_valid_config()
        userbot_config = config.get("USERBOT", {})
        if not userbot_config.get("ENABLED", False):
            logger.debug("📤 ПОИСК: Отправитель отключен в конфиге - поиск невозможен")
            return None

        client: Client = await get_userbot_client(user_id)
        if client is None:
            logger.error("❌ ПОИСК: Не удалось получить клиент отправителя")
            return None

        # Ищем подарки для перепродажи по ID, отсортированные по цене
        logger.debug("📞 ПОИСК: Вызов search_gifts_for_resale с сортировкой по цене")
        gifts_generator = client.search_gifts_for_resale(
            gift_id=gift_id,
            order=enums.GiftForResaleOrder.PRICE
        )

        checked = 0

        async for gift in gifts_generator:
            checked += 1

            # Нормализуем данные подарка
            gift_data = normalize_resale_gift(gift)

            # Показываем прогресс каждые 50 подарков
            if checked % 50 == 0:
                logger.debug(f"🔄 ПОИСК: Проверено {checked} подарков для ID {gift_id}")

            # Проверяем что подарок доступен за звезды
            if gift_data["available_for_stars"] and gift_data["price"] > 0:
                # Проверяем максимальную цену если задана
                if max_price is None or gift_data["price"] <= max_price:
                    logger.info(f"✅ ПОИСК: Найден подходящий подарок ID {gift_id}")
                    logger.info(f"🎁 ПОИСК: Название: {gift_data['name']}")
                    logger.info(f"💰 ПОИСК: Цена: ★{gift_data['price']:,}")
                    logger.info(f"🔗 ПОИСК: Ссылка: {gift_data['link']}")
                    logger.info(f"📊 ПОИСК: Найден после проверки {checked} подарков")

                    return gift_data
                else:
                    # Найден самый дешевый подарок, но он дороже лимита
                    logger.warning(f"💸 ПОИСК: Самый дешевый найденный подарок (★{gift_data['price']:,}) дороже лимита (★{max_price:,}) - {gift_data['link']}")
                    return None

        logger.info(f"❌ ПОИСК: Подходящий подарок ID {gift_id} не найден после проверки {checked} подарков")
        return None

    except Exception as e:
        logger.error(f"💥 ПОИСК: Ошибка поиска подарка ID {gift_id}: {e}")
        return None


def validate_gift_id(gift_id: str | int) -> int | None:
    """
    Валидирует и преобразует ID подарка в целое число.

    :param gift_id: ID подарка (строка или число)
    :return: Валидный ID как int или None если невалидный
    """
    logger.debug(f"✅ ВАЛИДАЦИЯ: Проверка Gift ID: {gift_id} (тип: {type(gift_id).__name__})")

    try:
        if isinstance(gift_id, str):
            gift_id_int = int(gift_id)
        elif isinstance(gift_id, int):
            gift_id_int = gift_id
        else:
            logger.error(f"❌ ВАЛИДАЦИЯ: Неподдерживаемый тип Gift ID: {type(gift_id).__name__}")
            return None

        # Простая проверка что ID не слишком маленький
        if gift_id_int < 1000000000:  # ID подарков обычно длинные
            logger.error(f"❌ ВАЛИДАЦИЯ: Gift ID слишком короткий: {gift_id_int}")
            return None

        logger.debug(f"✅ ВАЛИДАЦИЯ: Gift ID валиден: {gift_id_int}")
        return gift_id_int

    except (ValueError, TypeError) as e:
        logger.error(f"❌ ВАЛИДАЦИЯ: Ошибка преобразования Gift ID '{gift_id}': {e}")
        return None


async def check_gift_availability(user_id: int, gift_id: int) -> dict:
    """
    Простая проверка доступности конкретного типа подарка для перепродажи.
    НЕ ищет конкретные экземпляры и цены - только проверяет существование типа подарка.

    :param user_id: ID пользователя
    :param gift_id: ID типа подарка
    :return: Словарь с информацией о доступности
    """
    validated_id = validate_gift_id(gift_id)
    if validated_id is None:
        logger.error(f"❌ ПРОВЕРКА: Невалидный Gift ID: {gift_id}")
        return {
            "available": False,
            "error": "Невалидный ID подарка",
            "total_found": 0
        }

    try:
        config = await get_valid_config()
        userbot_config = config.get("USERBOT", {})
        if not userbot_config.get("ENABLED", False):
            logger.warning("⚠️ ПРОВЕРКА: Отправитель неактивен")
            return {
                "available": False,
                "error": "Отправитель не активен",
                "total_found": 0
            }

        client: Client = await get_userbot_client(user_id)
        if client is None:
            logger.error("❌ ПРОВЕРКА: Не удалось получить клиент отправителя")
            return {
                "available": False,
                "error": "Не удалось получить клиент отправителя",
                "total_found": 0
            }

        # Получаем все доступные подарки (базовые типы)
        available_gifts: list[Gift] = await client.get_available_gifts()

        # Ищем нужный ID среди доступных типов подарков
        target_gift = None
        for gift in available_gifts:
            gift_id_attr = getattr(gift, 'id', None)
            if str(gift_id_attr) == str(validated_id):
                target_gift = gift
                break

        if not target_gift:
            logger.warning(f"⚠️ ПРОВЕРКА: Подарок ID {validated_id} не найден среди доступных типов")
            return {
                "available": False,
                "error": "Подарок с таким ID не найден среди доступных типов",
                "total_found": 0
            }

        # Проверяем что есть количество для перепродажи
        resale_amount = getattr(target_gift, 'available_resale_amount', 0)
        title = getattr(target_gift, 'title', 'Unknown')

        # Обрабатываем None title
        if title is None:
            title = 'Unknown'

        if not resale_amount or resale_amount <= 0:
            logger.warning(f"⚠️ ПРОВЕРКА: Подарок '{title}' недоступен для перепродажи (количество: {resale_amount})")
            return {
                "available": False,
                "error": f"Подарок '{title}' не доступен для перепродажи (amount: {resale_amount})",
                "total_found": 0
            }

        logger.info(f"🎁 ПРОВЕРКА: Найден подарок: {title} (ID: {validated_id}) для перепродажи доступно: {resale_amount:,}")

        # Возвращаем результат БЕЗ поиска дешевых экземпляров
        result = {
            "available": True,
            "error": None,
            "total_found": resale_amount,
            "gift_name": title
        }

        return result

    except Exception as e:
        logger.error(f"💥 ПРОВЕРКА: Ошибка проверки подарка ID {gift_id}: {e}")
        return {
            "available": False,
            "error": f"Ошибка проверки: {str(e)}",
            "total_found": 0
        }