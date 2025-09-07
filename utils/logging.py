# utils/logging.py
"""
Модуль для настройки простого логирования в проекте.

Этот модуль содержит функции для:
- Инициализации логирования с заданным уровнем.
- Форматирования логов в удобочитаемом виде.
- Записи логов в текстовый файл.

Основные функции:
- setup_logging: Настраивает простое логирование с записью в файл.
"""

# --- Стандартные библиотеки ---
import logging
import os

def setup_logging(level: int = logging.INFO) -> None:
    """
    Инициализация простого логирования для проекта с записью в файл.

    :param level: Уровень логирования (по умолчанию logging.INFO)
    :return: None
    """
    # Создаем папку для логов если её нет
    logs_dir = "logs"
    os.makedirs(logs_dir, exist_ok=True)

    # Настраиваем форматтер
    formatter = logging.Formatter(
        "[{asctime}] [{levelname}] {name}: {message}",
        style="{",
        datefmt="%d.%m.%Y %H:%M:%S"
    )

    # Настраиваем корневой логгер
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Удаляем существующие хендлеры чтобы избежать дубликатов
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Консольный хендлер
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # Простой файловый хендлер без ротации
    file_handler = logging.FileHandler(
        filename=os.path.join(logs_dir, "bot.log"),
        encoding="utf-8",
        mode="a"  # Добавлять в конец файла
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)