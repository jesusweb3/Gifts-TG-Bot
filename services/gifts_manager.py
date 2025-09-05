# services/gifts_manager.py
"""
Модуль управления подарками для системы таргетов (перепродажа).

Этот модуль содержит функции для работы с подарками, включая:
- Кеширование результатов поиска по каждому таргету.
- Поиск подарков по конкретным ID с учетом цены.
- Фоновое обновление данных о доступных подарках.

Основные функции:
- userbot_targets_updater: Фоновая задача для обновления кеша по всем активным таргетам.
- get_target_gift: Возвращает лучший найденный подарок для конкретного таргета.
- update_target_cache: Обновляет кеш для одного таргета.
"""

# --- Стандартные библиотеки ---
import time
import random
import asyncio
import logging
from typing import Dict, Optional

# --- Внутренние модули ---
from services.config import get_valid_config, MORE_LOGS
from services.gifts_userbot import find_cheapest_gift_by_id

logger = logging.getLogger(__name__)

# Упрощенный кеш подарков по таргетам
targets_cache: Dict[int, Dict] = {}
last_global_update: float = 0


async def update_target_cache(user_id: int, target_index: int, target: dict) -> Optional[dict]:
    """
    Обновляет кеш для одного конкретного таргета.

    :param user_id: ID пользователя
    :param target_index: Индекс таргета в списке
    :param target: Данные таргета (GIFT_ID, MAX_PRICE, etc.)
    :return: Найденный подарок или None
    """
    gift_id = target.get("GIFT_ID")
    max_price = target.get("MAX_PRICE", 0)
    gift_name = target.get("GIFT_NAME", "🎁")

    if not gift_id:
        logger.warning(f"Таргет {target_index} не имеет GIFT_ID")
        return None

    try:
        # Конвертируем gift_id в int если это строка
        if isinstance(gift_id, str):
            gift_id = int(gift_id)

        if MORE_LOGS:
            logger.info(f"Обновление таргета {target_index}: {gift_name} (ID: {gift_id}, макс: {max_price})")

        # Ищем самый дешевый подарок по ID
        gift_data = await find_cheapest_gift_by_id(
            user_id=user_id,
            gift_id=gift_id,
            max_price=max_price,
            max_check=50
        )

        # Обновляем кеш
        targets_cache[target_index] = {
            "gift_data": gift_data,
            "last_update": time.time(),
            "target_info": {
                "gift_id": gift_id,
                "gift_name": gift_name,
                "max_price": max_price
            }
        }

        if gift_data:
            if MORE_LOGS:
                logger.info(f"Найден подарок для таргета {target_index}: {gift_data['name']} за {gift_data['price']} звезд")
        else:
            if MORE_LOGS:
                logger.info(f"Подарок для таргета {target_index} не найден в пределах {max_price} звезд")

        return gift_data

    except Exception as e:
        logger.error(f"Ошибка обновления таргета {target_index} (ID: {gift_id}): {e}")
        return None


async def userbot_targets_updater(user_id: int) -> None:
    """
    Запускает фоновую задачу для регулярного обновления кеша подарков по всем активным таргетам.

    :param user_id: Telegram ID владельца отправитель-сессии
    :return: None
    """
    global last_global_update

    while True:
        update_interval = 45  # Значение по умолчанию

        try:
            config = await get_valid_config()
            userbot_config = config.get("USERBOT", {})
            update_interval = userbot_config.get("UPDATE_INTERVAL", 45)

            # Проверяем что бот активен
            if not config.get("ACTIVE", False):
                await asyncio.sleep(5)
                continue

            # Получаем активные таргеты
            targets = config.get("TARGETS", [])
            enabled_targets = [(i, t) for i, t in enumerate(targets) if t.get("ENABLED", True)]

            if not enabled_targets:
                if MORE_LOGS:
                    logger.info("Нет активных таргетов для обновления")
                await asyncio.sleep(update_interval)
                continue

            if MORE_LOGS:
                logger.info(f"Обновление кеша для {len(enabled_targets)} активных таргетов")

            # Обновляем каждый активный таргет
            updated_count = 0
            for target_index, target in enabled_targets:
                try:
                    gift_data = await update_target_cache(user_id, target_index, target)
                    if gift_data:
                        updated_count += 1

                    # Небольшая пауза между запросами
                    await asyncio.sleep(2)

                except Exception as e:
                    logger.error(f"Ошибка обновления таргета {target_index}: {e}")
                    continue

            last_global_update = time.time()

            if MORE_LOGS:
                logger.info(f"Обновление завершено: {updated_count}/{len(enabled_targets)} таргетов имеют доступные подарки")

        except Exception as e:
            logger.error(f"Ошибка в userbot_targets_updater: {e}")

        # Случайная задержка для избежания паттернов
        delay = random.randint(update_interval, update_interval + 15)
        if MORE_LOGS:
            logger.info(f"Следующее обновление таргетов через {delay} секунд...")
        await asyncio.sleep(delay)


def get_target_gift(target_index: int) -> Optional[dict]:
    """
    Возвращает лучший найденный подарок для конкретного таргета из кеша.

    :param target_index: Индекс таргета в списке
    :return: Данные подарка или None если не найден
    """
    if target_index not in targets_cache:
        return None

    cache_entry = targets_cache[target_index]
    return cache_entry.get("gift_data")


def get_all_available_target_gifts(user_id: int) -> list[dict]:
    """
    Возвращает список всех доступных подарков для активных таргетов.

    :param user_id: ID пользователя (сохранен для совместимости)
    :return: Список подарков с дополнительной информацией о таргете
    """
    available_gifts = []

    for target_index, cache_entry in targets_cache.items():
        gift_data = cache_entry.get("gift_data")
        target_info = cache_entry.get("target_info", {})

        if gift_data:
            # Добавляем информацию о таргете к данным подарка
            enhanced_gift = gift_data.copy()
            enhanced_gift.update({
                "target_index": target_index,
                "target_gift_id": target_info.get("gift_id"),
                "target_gift_name": target_info.get("gift_name"),
                "target_max_price": target_info.get("max_price"),
                "last_update": cache_entry.get("last_update")
            })
            available_gifts.append(enhanced_gift)

    # Сортируем по цене (сначала самые дешевые)
    available_gifts.sort(key=lambda g: g.get("price", 0))

    return available_gifts


def clear_targets_cache() -> None:
    """
    Очищает кеш таргетов.
    """
    global targets_cache
    targets_cache.clear()
    logger.info("Кеш таргетов очищен")


def get_cache_stats() -> dict:
    """
    Возвращает статистику по кешу таргетов.

    :return: Словарь со статистикой
    """
    total_targets = len(targets_cache)
    with_gifts = sum(1 for entry in targets_cache.values() if entry.get("gift_data"))

    return {
        "total_targets": total_targets,
        "with_gifts": with_gifts,
        "last_global_update": last_global_update,
        "targets_details": {
            idx: {
                "has_gift": bool(entry.get("gift_data")),
                "last_update": entry.get("last_update"),
                "target_name": entry.get("target_info", {}).get("gift_name", "Unknown")
            }
            for idx, entry in targets_cache.items()
        }
    }