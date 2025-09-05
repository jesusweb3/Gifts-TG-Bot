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

    return {
        "id": collectible_id,
        "gift_id": getattr(gift, 'gift_id', None),
        "price": star_price or 0,
        "name": name,
        "link": link,
        "attributes": attributes,
        "resale_ton_only": resale_ton_only,
        "available_for_stars": star_price is not None and not resale_ton_only
    }


async def get_available_resale_gifts(user_id: int) -> list[dict]:
    """
    Получает список всех подарков доступных для перепродажи.

    :param user_id: Telegram ID владельца отправитель-сессии
    :return: Список словарей с доступными подарками для перепродажи
    """
    if not is_userbot_active(user_id):
        return []

    try:
        config = await get_valid_config()
        userbot_config = config.get("USERBOT", {})
        if not userbot_config.get("ENABLED", False):
            return []

        client: Client = await get_userbot_client(user_id)
        if client is None:
            logger.error("Не удалось получить объект клиента отправителя.")
            return []

        # Получаем подарки доступные для покупки
        available_gifts: list[Gift] = await client.get_available_gifts()
        if MORE_LOGS:
            logger.info(f"Получено {len(available_gifts)} базовых подарков от отправителя.")

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
            logger.info(f"Найдено {len(resale_gifts)} подарков доступных для перепродажи")

        return resale_gifts

    except Exception as e:
        logger.error(f"Ошибка получения подарков для перепродажи: {e}")
        return []


async def find_cheapest_gift_by_id(user_id: int, gift_id: int, max_price: int = None, max_check: int = 100) -> dict | None:
    """
    Находит самый дешевый подарок по ID за звезды (не TON).

    :param user_id: Telegram ID владельца отправитель-сессии
    :param gift_id: ID типа подарка для поиска
    :param max_price: Максимальная цена в звездах (если None - без ограничений)
    :param max_check: Максимальное количество подарков для проверки
    :return: Словарь с данными подарка или None если не найден
    """
    if not is_userbot_active(user_id):
        return None

    try:
        config = await get_valid_config()
        userbot_config = config.get("USERBOT", {})
        if not userbot_config.get("ENABLED", False):
            return None

        client: Client = await get_userbot_client(user_id)
        if client is None:
            logger.error("Не удалось получить объект клиента отправителя.")
            return None

        if MORE_LOGS:
            logger.info(f"Поиск самого дешевого подарка ID {gift_id} за звезды (макс. цена: {max_price})")

        # Ищем подарки для перепродажи по ID, отсортированные по цене
        gifts_generator = client.search_gifts_for_resale(
            gift_id=gift_id,
            order=enums.GiftForResaleOrder.PRICE
        )

        checked = 0

        async for gift in gifts_generator:
            checked += 1

            # Нормализуем данные подарка
            gift_data = normalize_resale_gift(gift)

            # Показываем прогресс каждые 25 подарков
            if checked % 25 == 0 and MORE_LOGS:
                logger.info(f"Проверено: {checked} подарков для ID {gift_id}...")

            # Проверяем что подарок доступен за звезды
            if gift_data["available_for_stars"] and gift_data["price"] > 0:
                # Проверяем максимальную цену если задана
                if max_price is None or gift_data["price"] <= max_price:
                    if MORE_LOGS:
                        logger.info(f"Найден подходящий подарок ID {gift_id} за {gift_data['price']} звезд (проверено {checked} шт)")
                    return gift_data

            # Ограничиваем количество проверок
            if checked >= max_check:
                if MORE_LOGS:
                    logger.info(f"Достигнут лимит проверок ({max_check}) для подарка ID {gift_id}")
                break

        if MORE_LOGS:
            logger.info(f"Подарок ID {gift_id} за звезды в пределах {max_price} не найден (проверено {checked} шт)")
        return None

    except Exception as e:
        logger.error(f"Ошибка поиска подарка ID {gift_id}: {e}")
        return None


def validate_gift_id(gift_id: str | int) -> int | None:
    """
    Валидирует и преобразует ID подарка в целое число.

    :param gift_id: ID подарка (строка или число)
    :return: Валидный ID как int или None если невалидный
    """
    try:
        if isinstance(gift_id, str):
            gift_id_int = int(gift_id)
        elif isinstance(gift_id, int):
            gift_id_int = gift_id
        else:
            return None

        # Простая проверка что ID не слишком маленький
        if gift_id_int < 1000000000:  # ID подарков обычно длинные
            return None

        return gift_id_int

    except (ValueError, TypeError):
        return None


async def check_gift_availability(user_id: int, gift_id: int) -> dict:
    """
    Проверяет доступность конкретного типа подарка для перепродажи.

    :param user_id: ID пользователя
    :param gift_id: ID типа подарка
    :return: Словарь с информацией о доступности
    """
    validated_id = validate_gift_id(gift_id)
    if validated_id is None:
        return {
            "available": False,
            "error": "Невалидный ID подарка",
            "total_found": 0,
            "cheapest_price": None
        }

    try:
        config = await get_valid_config()
        userbot_config = config.get("USERBOT", {})
        if not userbot_config.get("ENABLED", False):
            return {
                "available": False,
                "error": "Отправитель не активен",
                "total_found": 0,
                "cheapest_price": None
            }

        client: Client = await get_userbot_client(user_id)
        if client is None:
            return {
                "available": False,
                "error": "Не удалось получить клиент отправителя",
                "total_found": 0,
                "cheapest_price": None
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
            return {
                "available": False,
                "error": "Подарок с таким ID не найден среди доступных типов",
                "total_found": 0,
                "cheapest_price": None
            }

        # Проверяем что есть количество для перепродажи
        resale_amount = getattr(target_gift, 'available_resale_amount', 0)
        title = getattr(target_gift, 'title', 'Unknown')

        # Обрабатываем None title
        if title is None:
            title = 'Unknown'

        if not resale_amount or resale_amount <= 0:
            return {
                "available": False,
                "error": f"Подарок '{title}' не доступен для перепродажи (amount: {resale_amount})",
                "total_found": 0,
                "cheapest_price": None
            }

        # Теперь ищем самый дешевый экземпляр этого подарка
        cheapest_gift = await find_cheapest_gift_by_id(
            user_id=user_id,
            gift_id=validated_id,
            max_price=None,
            max_check=5  # Быстрая проверка
        )

        return {
            "available": True,
            "error": None,
            "total_found": resale_amount,
            "cheapest_price": cheapest_gift["price"] if cheapest_gift else None,
            "cheapest_link": cheapest_gift.get("link", "") if cheapest_gift else "",
            "gift_name": title
        }

    except Exception as e:
        return {
            "available": False,
            "error": f"Ошибка проверки: {str(e)}",
            "total_found": 0,
            "cheapest_price": None
        }