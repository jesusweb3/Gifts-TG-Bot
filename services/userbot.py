# services/userbot.py
"""
Модуль управления отправитель-сессией через Pyrogram.
Исправленная версия с четкой логикой активности и правильным предоставлением клиента.

Этот модуль содержит функции для:
- Создания, запуска и авторизации отправитель-сессии.
- Управления сессионным файлом и конфигурацией отправителя.
- Предоставления готового к работе клиента для других модулей.

Основные функции:
- is_userbot_active: Проверяет, активна ли отправитель-сессия.
- get_userbot_client: Возвращает готовый клиент для работы с API.
- try_start_userbot_from_config: Запускает отправитель-сессию из конфига.
"""

# --- Стандартные библиотеки ---
import logging
import os
import builtins
import asyncio

# --- Сторонние библиотеки ---
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from pyrogram import Client
from pyrogram.errors import (
    ApiIdInvalid,
    PhoneCodeInvalid,
    SessionPasswordNeeded,
    PasswordHashInvalid,
    PhoneNumberInvalid,
    FloodWait,
    BadRequest,
    RPCError,
    SecurityCheckMismatch
)

# --- Внутренние библиотеки ---
from services.config import (
    get_valid_config, save_config,
    DEVICE_MODEL, SYSTEM_VERSION, APP_VERSION, LANG_CODE, SYSTEM_LANG_CODE
)

logger = logging.getLogger(__name__)

sessions_dir = os.path.abspath("sessions")  # Папка для хранения сессий отправителя
os.makedirs(sessions_dir, exist_ok=True)

# Упрощенное хранение - один клиент для личного использования
_userbot_client: Client | None = None
_userbot_started: bool = False
_current_user_id: int | None = None


def is_userbot_active(user_id: int) -> bool:
    """
    Проверяет, активна ли отправитель-сессия.
    Сессия активна только если клиент создан, запущен, подключен и авторизован.

    :param user_id: ID пользователя
    :return: True если сессия полностью готова к работе
    """
    global _userbot_client, _userbot_started, _current_user_id

    # Базовые проверки
    if (_userbot_client is None or
            not _userbot_started or
            _current_user_id != user_id):
        logger.debug(f"📤 ОТПРАВИТЕЛЬ: Неактивен для пользователя {user_id} - базовые условия не выполнены")
        return False

    # Проверяем что клиент подключен
    if not _userbot_client.is_connected:
        logger.debug(f"📤 ОТПРАВИТЕЛЬ: Неактивен для пользователя {user_id} - клиент не подключен")
        return False

    logger.debug(f"📤 ОТПРАВИТЕЛЬ: Активен для пользователя {user_id} ✅")
    return True


async def get_userbot_client(user_id: int) -> Client | None:
    """
    Возвращает готовый к работе Pyrogram Client для user_id.
    Клиент гарантированно подключен и авторизован, готов для вызова API.

    :param user_id: ID пользователя
    :return: Готовый Pyrogram Client или None если недоступен
    """
    global _userbot_client

    logger.debug(f"📤 ОТПРАВИТЕЛЬ: Запрос клиента для пользователя {user_id}")

    # Проверяем активность через основную функцию
    if not is_userbot_active(user_id):
        logger.debug("❌ ОТПРАВИТЕЛЬ: Клиент недоступен - отправитель неактивен")
        return None

    # Дополнительная проверка готовности клиента
    try:
        # Быстрая проверка что сессия действительно работает
        logger.debug("🔍 ОТПРАВИТЕЛЬ: Проверка готовности клиента...")
        me = await _userbot_client.get_me()
        logger.debug(f"✅ ОТПРАВИТЕЛЬ: Клиент готов, авторизован как: {me.first_name}")
        return _userbot_client

    except Exception as e:
        logger.error(f"❌ ОТПРАВИТЕЛЬ: Клиент неисправен: {e}")
        # Сбрасываем состояние если клиент не работает
        await _reset_userbot_state()
        return None


async def _reset_userbot_state():
    """Сбрасывает состояние отправителя при ошибках"""
    global _userbot_client, _userbot_started, _current_user_id

    logger.warning("⚠️ ОТПРАВИТЕЛЬ: Сброс состояния из-за ошибки")

    if _userbot_client:
        try:
            if _userbot_client.is_connected:
                await _userbot_client.disconnect()
            await _userbot_client.stop()
        except:
            pass  # Игнорируем ошибки при остановке

    _userbot_client = None
    _userbot_started = False
    _current_user_id = None


async def is_userbot_premium(user_id: int) -> bool:
    """
    Проверяет наличие премиум подписки отправитель-сессии.

    :param user_id: ID пользователя
    :return: True если премиум аккаунт
    """
    client = await get_userbot_client(user_id)
    if client is None:
        logger.debug("📤 ОТПРАВИТЕЛЬ: Невозможно проверить премиум статус - клиент недоступен")
        return False

    try:
        logger.debug("📤 ОТПРАВИТЕЛЬ: Проверка премиум статуса")
        me = await client.get_me()
        is_premium = getattr(me, 'is_premium', False)
        logger.debug(f"📤 ОТПРАВИТЕЛЬ: Премиум статус: {'✅ Есть' if is_premium else '❌ Нет'}")
        return is_premium
    except Exception as e:
        logger.error(f"❌ ОТПРАВИТЕЛЬ: Ошибка при проверке премиум статуса: {e}")
        return False


async def try_start_userbot_from_config(user_id: int, bot_id: int) -> bool:
    """
    Проверяет, есть ли валидная отправитель-сессия для пользователя, и запускает её.
    Исправленная версия с правильной логикой запуска и проверки готовности.

    :param user_id: ID пользователя Telegram
    :param bot_id: ID бота (для совместимости)
    :return: True если сессия успешно запущена и готова к работе
    """
    global _userbot_client, _userbot_started, _current_user_id

    logger.debug(f"📤 ОТПРАВИТЕЛЬ: Попытка запуска отправителя для пользователя {user_id}")

    try:
        # Запрет интерактивного ввода
        builtins.input = lambda _: (_ for _ in ()).throw(RuntimeError())

        os.makedirs(sessions_dir, exist_ok=True)

        config = await get_valid_config()
        userbot_data = config.get("USERBOT", {})
        required_fields = ("API_ID", "API_HASH", "PHONE")
        session_name = f"userbot_{user_id}"
        session_path = os.path.join(sessions_dir, f"{session_name}.session")

        # Проверяем наличие обязательных данных в конфиге
        missing_fields = [field for field in required_fields if not userbot_data.get(field)]

        if missing_fields:
            logger.debug(f"📤 ОТПРАВИТЕЛЬ: Конфигурация не завершена - отсутствуют поля: {missing_fields}")
            _cleanup_session_files(session_path)
            await _clear_userbot_config()
            return False

        api_id = userbot_data["API_ID"]
        api_hash = userbot_data["API_HASH"]
        phone_number = userbot_data["PHONE"]

        # Проверяем наличие файла сессии
        if not os.path.exists(session_path):
            logger.debug("📤 ОТПРАВИТЕЛЬ: Файл сессии не найден - требуется авторизация")
            await _clear_userbot_config()
            return False

        logger.debug(f"📤 ОТПРАВИТЕЛЬ: Найден файл сессии: {session_path}")

        file_size = os.path.getsize(session_path)
        if file_size < 100:
            logger.warning(f"⚠️ ОТПРАВИТЕЛЬ: Файл сессии подозрительно мал ({file_size} байт) - возможно поврежден")
            _cleanup_session_files(session_path)
            await _clear_userbot_config()
            return False

        # Создаем клиент
        app: Client = await create_userbot_client(session_name, api_id, api_hash, phone_number, sessions_dir)

        try:
            logger.info("📤 ОТПРАВИТЕЛЬ: Запуск существующей сессии...")

            # Запускаем клиент
            await app.start()

            # ВАЖНО: Проверяем что клиент действительно авторизован
            logger.debug("📤 ОТПРАВИТЕЛЬ: Проверка авторизации...")
            me = await app.get_me()

            logger.info(
                f"✅ ОТПРАВИТЕЛЬ: Успешная авторизация как {me.first_name} (@{me.username or 'без username'}) ID: {me.id}")

            # Сохраняем данные аккаунта в конфиг
            config["USERBOT"]["USER_ID"] = me.id
            config["USERBOT"]["USERNAME"] = me.username
            config["USERBOT"]["FIRST_NAME"] = me.first_name or "Не указано"
            await save_config(config)
            logger.debug("📤 ОТПРАВИТЕЛЬ: Данные аккаунта сохранены в конфиг")

            # Устанавливаем глобальные переменные ТОЛЬКО после успешной проверки
            _userbot_client = app
            _userbot_started = True
            _current_user_id = user_id

            logger.info("🟢 ОТПРАВИТЕЛЬ: Отправитель успешно запущен и готов к работе")
            return True

        except Exception as e:
            logger.error(f"❌ ОТПРАВИТЕЛЬ: Сессия повреждена или не авторизована: {e}")

            try:
                await app.stop()
                logger.debug("📤 ОТПРАВИТЕЛЬ: Поврежденный клиент остановлен")
            except:
                pass

            logger.info("🗑️ ОТПРАВИТЕЛЬ: Удаление поврежденных файлов сессии")
            _cleanup_session_files(session_path)
            await _clear_userbot_config()
            return False

    except Exception as e:
        logger.error(f"💥 ОТПРАВИТЕЛЬ: Критическая ошибка при запуске отправителя: {e}")
        await _reset_userbot_state()
        return False


def _cleanup_session_files(session_path: str):
    """Удаляет файлы сессии."""
    logger.debug(f"🗑️ ОТПРАВИТЕЛЬ: Очистка файлов сессии: {session_path}")

    files_removed = 0
    try:
        if os.path.exists(session_path):
            os.remove(session_path)
            files_removed += 1
            logger.debug("🗑️ ОТПРАВИТЕЛЬ: Основной файл сессии удален")
    except Exception as rm_err:
        logger.error(f"❌ ОТПРАВИТЕЛЬ: Не удалось удалить основной файл сессии: {rm_err}")

    journal = session_path + "-journal"
    if os.path.exists(journal):
        try:
            os.remove(journal)
            files_removed += 1
            logger.debug("🗑️ ОТПРАВИТЕЛЬ: Журнал сессии удален")
        except Exception as j_err:
            logger.error(f"❌ ОТПРАВИТЕЛЬ: Не удалось удалить журнал сессии: {j_err}")

    if files_removed > 0:
        logger.debug(f"🗑️ ОТПРАВИТЕЛЬ: Удалено {files_removed} файлов сессии")


async def _clear_userbot_config():
    """Сбрасывает поля USERBOT в конфиге."""
    logger.debug("📤 ОТПРАВИТЕЛЬ: Сброс конфигурации отправителя")

    config = await get_valid_config()
    config["USERBOT"] = {
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
    await save_config(config)
    logger.debug("📤 ОТПРАВИТЕЛЬ: Конфигурация отправителя сброшена")


async def create_userbot_client(
        session_name: str,
        api_id: int,
        api_hash: str,
        phone: str,
        workdir: str,
) -> Client:
    """
    Создаёт экземпляр Pyrogram Client с фиксированными параметрами Desktop-клиента.

    :param session_name: Имя сессии
    :param api_id: API ID от my.telegram.org
    :param api_hash: API Hash от my.telegram.org
    :param phone: Номер телефона
    :param workdir: Рабочая директория для сессий
    :return: Настроенный Pyrogram Client
    """
    logger.debug(f"📤 ОТПРАВИТЕЛЬ: Создание клиента для сессии {session_name}")

    return Client(
        name=session_name,
        api_id=api_id,
        api_hash=api_hash,
        phone_number=phone,
        workdir=workdir,
        device_model=DEVICE_MODEL,
        system_version=SYSTEM_VERSION,
        app_version=APP_VERSION,
        lang_code=LANG_CODE,
        system_lang_code=SYSTEM_LANG_CODE,
        sleep_threshold=30,
        no_updates=True,
        skip_updates=True
    )


# === Функции авторизации (остаются без изменений) ===

async def start_userbot(message: Message, state) -> bool:
    """Инициирует подключение отправителя: отправляет код подтверждения."""
    global _userbot_client, _current_user_id

    builtins.input = lambda _: (_ for _ in ()).throw(RuntimeError())

    data = await state.get_data()
    user_id = message.from_user.id

    session_name = f"userbot_{user_id}"
    api_id = data["api_id"]
    api_hash = data["api_hash"]
    phone_number = data["phone"]

    app: Client = await create_userbot_client(session_name, api_id, api_hash, phone_number, sessions_dir)

    logger.debug("📤 ОТПРАВИТЕЛЬ: Подключение к Telegram")
    await app.connect()

    try:
        sent = await app.send_code(phone_number)
        _userbot_client = app
        _current_user_id = user_id
        await state.update_data(phone_code_hash=sent.phone_code_hash, phone=phone_number)

        logger.info("✅ ОТПРАВИТЕЛЬ: Код подтверждения успешно отправлен")
        return True

    except ApiIdInvalid:
        logger.error("❌ ОТПРАВИТЕЛЬ: Неверный api_id и api_hash")
        await message.answer("🚫 Неверный api_id и api_hash. Проверьте данные.")
        return False
    except PhoneNumberInvalid:
        logger.error(f"❌ ОТПРАВИТЕЛЬ: Неверный номер телефона: {phone_number}")
        await message.answer("🚫 Неверный номер телефона.")
        return False
    except FloodWait as e:
        logger.warning(f"⚠️ ОТПРАВИТЕЛЬ: Слишком много запросов - ожидание {e.value} секунд")
        await message.answer(f"🚫 Слишком много запросов. Подождите {e.value} секунд.")
        return False
    except Exception as e:
        logger.error(f"💥 ОТПРАВИТЕЛЬ: Ошибка при отправке кода: {e}")
        await message.answer(f"🚫 Ошибка: {e}")
        return False
    finally:
        if not app.is_connected:
            await app.disconnect()
            return False


async def continue_userbot_signin(call: CallbackQuery, state: FSMContext) -> tuple[bool, bool, bool]:
    """Продолжает авторизацию с кодом подтверждения."""
    global _userbot_client, _userbot_started, _current_user_id

    data = await state.get_data()
    user_id = call.from_user.id
    code = data["code"]
    attempts = data.get("code_attempts", 0)

    if not _userbot_client:
        logger.error("❌ ОТПРАВИТЕЛЬ: Клиент не найден")
        await call.message.answer("🚫 Клиент не найден. Попробуйте сначала.")
        return False, False, False

    phone = data["phone"]
    phone_code_hash = data["phone_code_hash"]
    api_id = data["api_id"]
    api_hash = data["api_hash"]

    try:
        await _userbot_client.sign_in(
            phone_number=phone,
            phone_code_hash=phone_code_hash,
            phone_code=code
        )

        # Проверка авторизации
        me = await _userbot_client.get_me()

        # Устанавливаем статус
        _userbot_started = True
        _current_user_id = user_id

        # Сохраняем данные в конфиг
        config = await get_valid_config()
        config["USERBOT"]["API_ID"] = api_id
        config["USERBOT"]["API_HASH"] = api_hash
        config["USERBOT"]["PHONE"] = phone
        config["USERBOT"]["USER_ID"] = me.id
        config["USERBOT"]["USERNAME"] = me.username
        config["USERBOT"]["FIRST_NAME"] = me.first_name or "Не указано"
        config["USERBOT"]["ENABLED"] = True
        await save_config(config)

        logger.info(f"✅ ОТПРАВИТЕЛЬ: Авторизация завершена как {me.first_name}")
        return True, False, False

    except PhoneCodeInvalid:
        attempts += 1
        await state.update_data(code_attempts=attempts)
        if attempts < 3:
            logger.warning(f"⚠️ ОТПРАВИТЕЛЬ: Неверный код (попытка {attempts}/3)")
            return False, False, True  # retry
        else:
            logger.error("❌ ОТПРАВИТЕЛЬ: Превышено количество попыток")
            return False, False, False
    except SessionPasswordNeeded:
        logger.info("🔐 ОТПРАВИТЕЛЬ: Требуется облачный пароль")
        return True, True, False
    except Exception as e:
        logger.error(f"💥 ОТПРАВИТЕЛЬ: Ошибка при проверке кода: {e}")
        return False, False, False


async def finish_userbot_signin(message: Message, state) -> tuple[bool, bool]:
    """Завершает авторизацию после ввода пароля."""
    global _userbot_client, _userbot_started, _current_user_id

    data = await state.get_data()
    user_id = message.from_user.id

    if not _userbot_client:
        logger.error("❌ ОТПРАВИТЕЛЬ: Клиент не найден при проверке пароля")
        return False, False

    password = data["password"]
    api_id = data["api_id"]
    api_hash = data["api_hash"]
    phone = data["phone"]
    attempts = data.get("password_attempts", 0)

    try:
        await _userbot_client.check_password(password)
        me = await _userbot_client.get_me()

        _userbot_started = True
        _current_user_id = user_id

        # Сохраняем данные в конфиг
        config = await get_valid_config()
        config["USERBOT"]["API_ID"] = api_id
        config["USERBOT"]["API_HASH"] = api_hash
        config["USERBOT"]["PHONE"] = phone
        config["USERBOT"]["USER_ID"] = me.id
        config["USERBOT"]["USERNAME"] = me.username
        config["USERBOT"]["FIRST_NAME"] = me.first_name or "Не указано"
        config["USERBOT"]["ENABLED"] = True
        await save_config(config)

        logger.info(f"✅ ОТПРАВИТЕЛЬ: Авторизация завершена как {me.first_name}")
        return True, False

    except PasswordHashInvalid:
        attempts += 1
        await state.update_data(password_attempts=attempts)
        if attempts < 3:
            logger.warning(f"⚠️ ОТПРАВИТЕЛЬ: Неверный пароль (попытка {attempts}/3)")
            return False, True  # retry
        else:
            logger.error("❌ ОТПРАВИТЕЛЬ: Превышено количество попыток ввода пароля")
            return False, False
    except Exception as e:
        logger.error(f"💥 ОТПРАВИТЕЛЬ: Ошибка при проверке пароля: {e}")
        return False, False


async def delete_userbot_session(call: CallbackQuery, user_id: int) -> bool:
    """Полностью удаляет отправитель-сессию."""
    global _userbot_client, _userbot_started, _current_user_id

    logger.info(f"🗑️ ОТПРАВИТЕЛЬ: Начало удаления сессии для пользователя {user_id}")

    session_name = f"userbot_{user_id}"
    session_path = os.path.join(sessions_dir, f"{session_name}.session")

    # Останавливаем клиент
    if _userbot_client:
        try:
            if _userbot_client.is_connected:
                await _userbot_client.disconnect()
                await asyncio.sleep(0.5)
            if _userbot_started:
                await _userbot_client.stop()
                await asyncio.sleep(1.0)
            logger.info("✅ ОТПРАВИТЕЛЬ: Клиент успешно остановлен")
        except Exception as e:
            logger.warning(f"⚠️ ОТПРАВИТЕЛЬ: Ошибка при остановке клиента: {e}")

    # Очищаем глобальные переменные
    _userbot_client = None
    _userbot_started = False
    _current_user_id = None

    await asyncio.sleep(1.0)

    # Удаляем файлы сессии
    max_attempts = 3
    for attempt in range(max_attempts):
        try:
            _cleanup_session_files(session_path)
            logger.info("✅ ОТПРАВИТЕЛЬ: Файлы сессии успешно удалены")
            break
        except Exception as e:
            if attempt < max_attempts - 1:
                logger.warning(f"⚠️ ОТПРАВИТЕЛЬ: Попытка {attempt + 1}/{max_attempts} удаления файлов не удалась: {e}")
                await asyncio.sleep(1.0)
            else:
                logger.error(f"❌ ОТПРАВИТЕЛЬ: Не удалось удалить файлы сессии: {e}")

    # Очищаем конфиг
    await _clear_userbot_config()

    logger.info("✅ ОТПРАВИТЕЛЬ: Сессия полностью удалена")
    return True