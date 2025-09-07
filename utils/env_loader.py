"""
Модуль для загрузки переменных окружения.

Этот модуль проверяет наличие файла .env и загружает переменные окружения из него, если файл существует.
Если файл .env отсутствует, переменные загружаются из системных переменных окружения.

Основные функции:
- get_env_variable: Получает значение переменной окружения с возможностью указания значения по умолчанию.
"""

import os
import logging
from dotenv import load_dotenv
from utils.logging import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

# Проверяем наличие файла .env и загружаем переменные, если файл существует
if os.path.exists(".env"):
    load_dotenv(override=False)
else:
    logger.warning("Файл .env не найден")

def get_env_variable(key: str, default=None):
    return os.getenv(key) or os.environ.get(key, default)