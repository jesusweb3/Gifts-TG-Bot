# services/gifts_manager.py
"""
Модуль управления подарками для системы таргетов (перепродажа).

Этот модуль содержит функции для работы с подарками, включая:
- Кеширование результатов поиска по каждому таргету.
- Поиск подарков по конкретным ID с учетом цены.
- Фоновое обновление данных о доступных подарках.
- Правильная логика: НЕ очищаем кеш после покупки, продолжаем мониторинг новых экземпляров.

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
        logger.warning(f"⚠️ КЕШИРОВАНИЕ: Таргет #{target_index} не имеет GIFT_ID")
        return None

    try:
        # Конвертируем gift_id в int если это строка
        if isinstance(gift_id, str):
            gift_id = int(gift_id)

        logger.debug(
            f"🔄 КЕШИРОВАНИЕ: Обновление таргета #{target_index}: {gift_name} (ID: {gift_id}, лимит: ★{max_price:,})")

        # Ищем самый дешевый подарок по ID
        gift_data = await find_cheapest_gift_by_id(
            user_id=user_id,
            gift_id=gift_id,
            max_price=max_price
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
            logger.debug(
                f"✅ КЕШИРОВАНИЕ: Найден подарок для таргета #{target_index}: {gift_data['name']} за ★{gift_data['price']:,}")
        else:
            logger.debug(f"📦 КЕШИРОВАНИЕ: Подарок для таргета #{target_index} не найден в пределах ★{max_price:,}")

        return gift_data

    except ValueError as e:
        logger.error(f"❌ КЕШИРОВАНИЕ: Неверный GIFT_ID для таргета #{target_index}: {gift_id} - {e}")
        return None
    except Exception as e:
        logger.error(f"💥 КЕШИРОВАНИЕ: Ошибка обновления таргета #{target_index} (ID: {gift_id}): {e}")
        return None


async def userbot_targets_updater(user_id: int) -> None:
    """
    Запускает фоновую задачу для регулярного обновления кеша подарков по всем активным таргетам.

    :param user_id: Telegram ID владельца отправитель-сессии
    :return: None
    """
    global last_global_update

    cycle_count = 0
    last_log_time = 0

    try:
        while True:
            cycle_count += 1
            current_time = time.time()
            update_interval = 45  # Значение по умолчанию

            try:
                config = await get_valid_config()
                userbot_config = config.get("USERBOT", {})
                update_interval = userbot_config.get("UPDATE_INTERVAL", 45)

                # Проверяем что бот активен
                if not config.get("ACTIVE", False):
                    # Логируем деактивацию только раз в 5 минут
                    if current_time - last_log_time > 300:
                        logger.debug("⏸️ ВОРКЕР ТАРГЕТОВ: Система неактивна - ожидание активации")
                        last_log_time = current_time
                    await asyncio.sleep(5)
                    continue

                # Получаем активные таргеты
                targets = config.get("TARGETS", [])
                enabled_targets = [(i, t) for i, t in enumerate(targets) if t.get("ENABLED", True)]

                if not enabled_targets:
                    # Логируем отсутствие таргетов только раз в 5 минут
                    if current_time - last_log_time > 300:
                        logger.debug("📋 ВОРКЕР ТАРГЕТОВ: Нет активных таргетов для обновления")
                        last_log_time = current_time
                    await asyncio.sleep(update_interval)
                    continue

                # Обновляем каждый активный таргет БЕЗ избыточного логирования
                updated_count = 0
                found_gifts_count = 0

                for target_index, target in enabled_targets:
                    try:
                        gift_data = await update_target_cache(user_id, target_index, target)
                        updated_count += 1

                        if gift_data:
                            found_gifts_count += 1

                        # Небольшая пауза между запросами (2-4 секунды)
                        delay = random.uniform(2.0, 4.0)
                        await asyncio.sleep(delay)

                    except asyncio.CancelledError:
                        logger.info("🛑 ВОРКЕР ТАРГЕТОВ: Воркер остановлен по запросу")
                        raise
                    except Exception as e:
                        logger.error(f"💥 ВОРКЕР ТАРГЕТОВ: Ошибка обновления таргета #{target_index}: {e}")
                        continue

                last_global_update = time.time()

                # Логируем результат обновления только если что-то найдено
                if found_gifts_count > 0:
                    logger.debug(
                        f"✅ ВОРКЕР ТАРГЕТОВ: Обновление завершено - найдены подарки для {found_gifts_count}/{len(enabled_targets)} таргетов")

            except asyncio.CancelledError:
                logger.info("🛑 ВОРКЕР ТАРГЕТОВ: Воркер остановлен по запросу")
                raise
            except Exception as e:
                logger.error(f"💥 ВОРКЕР ТАРГЕТОВ: Ошибка в цикле обновления: {e}")

            # Случайная задержка для избежания паттернов (45-60 секунд)
            delay = random.randint(update_interval, update_interval + 15)

            # Логируем задержку только при включенном подробном логировании
            if MORE_LOGS:
                logger.debug(f"⏳ ВОРКЕР ТАРГЕТОВ: Следующее обновление через {delay} секунд")

            await asyncio.sleep(delay)

    except asyncio.CancelledError:
        logger.info("🛑 ВОРКЕР ТАРГЕТОВ: Воркер остановлен")
        raise
    except Exception as e:
        logger.error(f"💥 ВОРКЕР ТАРГЕТОВ: Критическая ошибка воркера: {e}")
    finally:
        logger.info("🏁 ВОРКЕР ТАРГЕТОВ: Завершение работы воркера обновления таргетов")


def get_target_gift(target_index: int) -> Optional[dict]:
    """
    Возвращает лучший найденный подарок для конкретного таргета из кеша.

    :param target_index: Индекс таргета в списке
    :return: Данные подарка или None если не найден
    """
    logger.debug(f"📦 КЕШИРОВАНИЕ: Запрос подарка для таргета #{target_index}")

    if target_index not in targets_cache:
        logger.debug(f"📦 КЕШИРОВАНИЕ: Таргет #{target_index} не найден в кеше")
        return None

    cache_entry = targets_cache[target_index]
    gift_data = cache_entry.get("gift_data")

    if gift_data:
        logger.debug(
            f"✅ КЕШИРОВАНИЕ: Найден подарок для таргета #{target_index}: {gift_data['name']} за ★{gift_data['price']:,}")
    else:
        logger.debug(f"📦 КЕШИРОВАНИЕ: Подарок для таргета #{target_index} отсутствует в кеше")

    return gift_data


def get_all_available_target_gifts(user_id: int) -> list[dict]:
    """
    Возвращает список всех доступных подарков для активных таргетов.

    :param user_id: ID пользователя (сохранен для совместимости)
    :return: Список подарков с дополнительной информацией о таргете
    """
    logger.debug(f"📦 КЕШИРОВАНИЕ: Запрос всех доступных подарков для пользователя {user_id}")

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

    logger.debug(f"📦 КЕШИРОВАНИЕ: Возвращено {len(available_gifts)} доступных подарков")

    if available_gifts:
        cheapest_price = available_gifts[0].get("price", 0)
        most_expensive_price = available_gifts[-1].get("price", 0)
        logger.debug(f"📦 КЕШИРОВАНИЕ: Диапазон цен: ★{cheapest_price:,} - ★{most_expensive_price:,}")

    return available_gifts


def clear_targets_cache() -> None:
    """
    Очищает весь кеш таргетов.
    """
    global targets_cache

    cache_size = len(targets_cache)
    targets_cache.clear()

    logger.info(f"🗑️ КЕШИРОВАНИЕ: Кеш таргетов очищен ({cache_size} записей удалено)")


def get_cache_stats() -> dict:
    """
    Возвращает статистику по кешу таргетов.

    :return: Словарь со статистикой
    """
    total_targets = len(targets_cache)
    with_gifts = sum(1 for entry in targets_cache.values() if entry.get("gift_data"))

    stats = {
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

    logger.debug(f"📊 КЕШИРОВАНИЕ: Статистика кеша - всего таргетов: {total_targets}, с подарками: {with_gifts}")

    return stats