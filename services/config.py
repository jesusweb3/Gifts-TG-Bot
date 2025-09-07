# services/config.py
"""
Модуль конфигурации с системой таргетов.

Этот модуль содержит функции для:
- Управления конфигурацией с системой таргетов подарков.
- Настройки отправителя (отправитель) и получателя.
- Управления таргетами (добавление, удаление, обновление).
- Форматирования данных для отображения в меню.

Основные функции:
- ensure_config: Гарантирует существование config.json.
- load_config: Загружает конфиг из файла.
- save_config: Сохраняет конфиг в файл.
- get_valid_config: Загружает и валидирует конфиг.
- add_target/remove_target/update_target: Управление таргетами.
- format_config_summary: Формирует текст для главного меню.
"""

# --- Стандартные библиотеки ---
import json
import os
import logging

# --- Сторонние библиотеки ---
import aiofiles

logger = logging.getLogger(__name__)

VERSION = '1.0.0'  # Версия приложения (система таргетов)
CONFIG_PATH = "config.json"  # Путь к файлу конфигурации
MORE_LOGS = False  # Логировать больше информации в консоль
DEFAULT_BOT_DELAY = 1.0  # Задержка бота по умолчанию

# Фиксированные параметры устройства для отправитель сессии
DEVICE_MODEL = "Desktop"
SYSTEM_VERSION = "Windows 10"
APP_VERSION = "1.0.0"
LANG_CODE = "en"
SYSTEM_LANG_CODE = "en"


def default_config() -> dict:
    """
    Дефолтная конфигурация с системой таргетов.
    :return: Словарь конфигурации
    """
    return {
        "ACTIVE": False,
        "LAST_MENU_MESSAGE_ID": None,
        "TARGET_USER_ID": None,
        "TARGET_CHAT_ID": None,
        "TARGET_TYPE": None,
        "TARGETS": [],
        "USERBOT": {
            "API_ID": None,
            "API_HASH": None,
            "PHONE": None,
            "USER_ID": None,
            "USERNAME": None,
            "FIRST_NAME": None,
            "BALANCE": 0,
            "ENABLED": True,
            "UPDATE_INTERVAL": 45
        }
    }


async def ensure_config(path: str = CONFIG_PATH):
    """
    Гарантирует существование config.json.
    :param path: Путь к файлу конфигурации
    """
    if not os.path.exists(path):
        async with aiofiles.open(path, mode="w", encoding="utf-8") as f:
            await f.write(json.dumps(default_config(), indent=2))


async def load_config(path: str = CONFIG_PATH) -> dict:
    """
    Загружает конфиг из файла. Гарантирует, что файл существует.
    :param path: Путь к файлу конфигурации
    :return: Словарь конфигурации
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"Файл {path} не найден. Используйте ensure_config.")
    async with aiofiles.open(path, mode="r", encoding="utf-8") as f:
        data = await f.read()
        return json.loads(data)


async def save_config(config: dict, path: str = CONFIG_PATH):
    """
    Сохраняет конфиг в файл.
    :param config: Словарь конфигурации
    :param path: Путь к файлу
    """
    async with aiofiles.open(path, mode="w", encoding="utf-8") as f:
        await f.write(json.dumps(config, indent=2))


def simple_validate_config(config: dict) -> dict:
    """
    Простая валидация конфига - заполняет отсутствующие поля значениями по умолчанию.
    :param config: Словарь конфигурации
    :return: Валидированный конфиг
    """
    default = default_config()

    # Заполняем отсутствующие верхнеуровневые поля
    for key, default_value in default.items():
        if key not in config:
            config[key] = default_value

    # Заполняем отсутствующие поля в USERBOT
    if "USERBOT" not in config or not isinstance(config["USERBOT"], dict):
        config["USERBOT"] = default["USERBOT"]
    else:
        for key, default_value in default["USERBOT"].items():
            if key not in config["USERBOT"]:
                config["USERBOT"][key] = default_value

    # Валидируем TARGETS
    if "TARGETS" not in config or not isinstance(config["TARGETS"], list):
        config["TARGETS"] = []
    else:
        # Простая валидация каждого таргета
        valid_targets = []
        for target in config["TARGETS"]:
            if isinstance(target, dict) and target.get("GIFT_ID") and target.get("GIFT_NAME"):
                valid_target = {
                    "GIFT_ID": str(target.get("GIFT_ID", "")),
                    "GIFT_NAME": str(target.get("GIFT_NAME", "🎁")),
                    "MAX_PRICE": int(target.get("MAX_PRICE", 10000)),
                    "ENABLED": bool(target.get("ENABLED", True))
                }
                valid_targets.append(valid_target)
        config["TARGETS"] = valid_targets

    return config


async def get_valid_config(path: str = CONFIG_PATH) -> dict:
    """
    Загружает, валидирует и при необходимости обновляет config.json.
    :param path: Путь к файлу конфигурации
    :return: Валидированный конфиг
    """
    await ensure_config(path)
    config = await load_config(path)
    validated = simple_validate_config(config)

    # Если есть изменения после валидации, сохранить
    if validated != config:
        await save_config(validated, path)

    return validated


async def update_config_from_env(path: str = CONFIG_PATH, config_data: str = None):
    """
    Обновляет конфиг из переменной среды CONFIG_DATA.
    :param path: Путь к файлу конфигурации
    :param config_data: Данные конфигурации в формате JSON
    """
    try:
        config_dict = json.loads(config_data)
    except json.JSONDecodeError as e:
        logger.error(f"CONFIG_DATA не является валидным JSON: {e}")
        return

    try:
        async with aiofiles.open(path, mode="w", encoding="utf-8") as f:
            await f.write(json.dumps(config_dict, indent=2, ensure_ascii=False))
        logger.info(f"Конфиг успешно обновлён из переменной среды CONFIG_DATA.")
    except OSError as e:
        logger.error(f"Ошибка при сохранении конфига из CONFIG_DATA: {e}")


async def add_target(config: dict, gift_id: str, gift_name: str, max_price: int, save: bool = True) -> dict:
    """
    Добавляет новый таргет в конфиг.
    :param config: Словарь конфигурации
    :param gift_id: ID подарка
    :param gift_name: Название/эмодзи подарка
    :param max_price: Максимальная цена для покупки
    :param save: Сохранять ли конфиг
    :return: Обновлённый конфиг
    """
    new_target = {
        "GIFT_ID": str(gift_id),
        "GIFT_NAME": str(gift_name),
        "MAX_PRICE": int(max_price),
        "ENABLED": True
    }
    config.setdefault("TARGETS", []).append(new_target)
    if save:
        await save_config(config)
    return config


async def remove_target(config: dict, index: int, save: bool = True) -> dict:
    """
    Удаляет таргет по индексу.
    :param config: Словарь конфигурации
    :param index: Индекс таргета
    :param save: Сохранять ли конфиг
    :return: Обновлённый конфиг
    """
    if "TARGETS" not in config or index >= len(config["TARGETS"]):
        raise IndexError("Таргет не найден")
    config["TARGETS"].pop(index)
    if save:
        await save_config(config)
    return config


async def update_target(config: dict, index: int, gift_id: str = None, max_price: int = None, enabled: bool = None,
                        save: bool = True) -> dict:
    """
    Обновляет таргет по индексу.
    :param config: Словарь конфигурации
    :param index: Индекс таргета
    :param gift_id: Новый ID подарка (опционально)
    :param max_price: Новая максимальная цена (опционально)
    :param enabled: Новый статус включен/выключен (опционально)
    :param save: Сохранять ли конфиг
    :return: Обновлённый конфиг
    """
    if "TARGETS" not in config or index >= len(config["TARGETS"]):
        raise IndexError("Таргет не найден")

    target = config["TARGETS"][index]
    if gift_id is not None:
        target["GIFT_ID"] = str(gift_id)
    if max_price is not None:
        target["MAX_PRICE"] = int(max_price)
    if enabled is not None:
        target["ENABLED"] = bool(enabled)

    if save:
        await save_config(config)
    return config


def format_config_summary(config: dict, user_id: int) -> str:
    """
    Формирует текст для главного меню с системой таргетов.
    :param config: Вся конфигурация (словарь)
    :param user_id: ID пользователя для отображения "Вы"
    :return: Готовый HTML-текст для меню
    """
    status_text = "🟢 Активен" if config.get("ACTIVE") else "🔴 Неактивен"
    userbot = config.get("USERBOT", {})
    userbot_balance = userbot.get("BALANCE", 0)
    userbot_first_name = userbot.get("FIRST_NAME", "Не указано")
    userbot_username = userbot.get("USERNAME")
    session_state = bool(userbot.get("API_ID") and userbot.get("API_HASH") and userbot.get("PHONE"))

    # Отображение отправителя
    if session_state:
        sender_display = f"{userbot_first_name}"
        if userbot_username:
            sender_display += f" (@{userbot_username})"
    else:
        sender_display = "Не подключен"

    # Отображение получателя
    target_display = get_target_display_local(
        config.get("TARGET_USER_ID"),
        config.get("TARGET_CHAT_ID"),
        user_id
    )

    # Подсчет таргетов
    targets = config.get("TARGETS", [])
    enabled_targets = [t for t in targets if t.get("ENABLED", True)]

    lines = [
        f"🚦 <b>Статус:</b> {status_text}",
        f"\n📤 <b>Отправитель:</b> {sender_display}",
        f"📥 <b>Получатель:</b> {target_display}",
        f"\n🎯 <b>Таргетов:</b> {len(enabled_targets)} из {len(targets)}"
    ]

    # Показываем первые 3 таргета
    for i, target in enumerate(enabled_targets[:3]):
        gift_name = target.get("GIFT_NAME", "🎁")
        max_price = target.get("MAX_PRICE", 0)
        lines.append(f"  • {gift_name} до ★{max_price:,}")

    if len(enabled_targets) > 3:
        lines.append(f"  • и ещё {len(enabled_targets) - 3}...")

    # Добавляем баланс отправителя
    if session_state:
        lines.append(f"\n💰 <b>Баланс:</b> {userbot_balance:,} ★")
    else:
        lines.append(f"\n💰 <b>Баланс:</b> Отправитель не подключён")

    return "\n".join(lines)


def get_target_display_local(target_user_id: int, target_chat_id: str, user_id: int) -> str:
    """
    Возвращает строковое описание получателя подарка.
    :param target_user_id: ID пользователя
    :param target_chat_id: ID чата
    :param user_id: ID текущего пользователя
    :return: строка для меню
    """
    if target_chat_id:
        return f"{target_chat_id}"
    elif target_user_id and str(target_user_id) == str(user_id):
        return f"<code>{target_user_id}</code> (Вы)"
    elif target_user_id:
        return f"<code>{target_user_id}</code>"
    else:
        return "Не указан"