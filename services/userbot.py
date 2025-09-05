# services/userbot.py
"""
Модуль управления отправитель-сессией через Pyrogram (упрощенная версия).

Этот модуль содержит функции для:
- Создания, запуска и авторизации отправитель-сессии.
- Управления сессионным файлом и конфигурацией отправителя.
- Получения баланса звёзд через отправитель.
- Отправки сообщений от имени отправителя.

Основные функции:
- is_userbot_active: Проверяет, активна ли отправитель-сессия.
- try_start_userbot_from_config: Запускает отправитель-сессию из конфига.
- create_userbot_client: Создаёт экземпляр Pyrogram Client для отправителя.
- start_userbot: Инициирует подключение отправителя.
- continue_userbot_signin: Продолжает авторизацию отправителя.
- finish_userbot_signin: Завершает авторизацию отправителя.
- delete_userbot_session: Удаляет отправитель-сессию.
- get_userbot_stars_balance: Получает баланс звёзд через отправитель.
"""

# --- Стандартные библиотеки ---
import logging
import os
import builtins
import random

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
from services.config import get_valid_config, save_config, DEVICE_MODELS, SYSTEM_VERSIONS, APP_VERSIONS

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
    """
    global _userbot_client, _userbot_started, _current_user_id
    return (_userbot_client is not None and
            _userbot_started and
            _current_user_id is not None and
            _current_user_id == user_id)


async def is_userbot_premium(user_id: int) -> bool:
    """
    Проверяет наличие премиум подписки отправитель-сессии.
    """
    global _userbot_client
    if not is_userbot_active(user_id) or _userbot_client is None:
        return False

    try:
        me = await _userbot_client.get_me()
        return me.is_premium
    except Exception as e:
        logger.error(f"Ошибка при проверке премиум статуса: {e}")
        return False


async def try_start_userbot_from_config(user_id: int, bot_id: int) -> bool:
    """
    Проверяет, есть ли валидная отправитель-сессия для пользователя, и запускает её.
    Сохраняет имя аккаунта в конфиг для отображения отправителя.
    """
    global _userbot_client, _userbot_started, _current_user_id

    try:
        # Запрет интерактивного ввода
        builtins.input = lambda _: (_ for _ in ()).throw(RuntimeError())

        os.makedirs(sessions_dir, exist_ok=True)

        config = await get_valid_config()
        userbot_data = config.get("USERBOT", {})
        required_fields = ("API_ID", "API_HASH", "PHONE")
        session_name = f"userbot_{user_id}"
        session_path = os.path.join(sessions_dir, f"{session_name}.session")

        # Если конфиг невалидный — удалить сессию, если она есть
        if not all(userbot_data.get(k) for k in required_fields):
            logger.warning("Отсутствуют обязательные данные в конфиге.")
            _cleanup_session_files(session_path)
            await _clear_userbot_config()
            return False

        api_id = userbot_data["API_ID"]
        api_hash = userbot_data["API_HASH"]
        phone_number = userbot_data["PHONE"]

        app: Client = await create_userbot_client(session_name, api_id, api_hash, phone_number, sessions_dir)

        if os.path.exists(session_path):
            if os.path.getsize(session_path) < 100:
                logger.error("Сессионный файл подозрительно мал — возможно, повреждён.")

            try:
                await app.start()
                me = await app.get_me()
                logger.info(f"Авторизован как {me.first_name} ({me.id})")

                # Сохраняем данные аккаунта в конфиг для отображения отправителя
                config["USERBOT"]["USER_ID"] = me.id
                config["USERBOT"]["USERNAME"] = me.username
                config["USERBOT"]["FIRST_NAME"] = me.first_name or "Не указано"
                await save_config(config)

                # Устанавливаем глобальные переменные
                _userbot_client = app
                _userbot_started = True
                _current_user_id = user_id

                return True

            except Exception as e:
                logger.error(f"Сессия повреждена или не завершена: {e}")
                try:
                    await app.stop()
                except Exception as stop_err:
                    logger.error(f"Не удалось остановить клиент: {stop_err}")

                _cleanup_session_files(session_path)

        else:
            logger.info("Файл сессии не найден. Авторизация не выполняется.")

        # Очистка USERBOT из конфига
        await _clear_userbot_config()
        return False

    except Exception as e:
        logger.error(f"Ошибка при запуске отправителя: {e}")
        return False


def _cleanup_session_files(session_path: str):
    """Удаляет файлы сессии."""
    try:
        if os.path.exists(session_path):
            os.remove(session_path)
            logger.info("Удалён .session файл.")
    except Exception as rm_err:
        logger.error(f"Не удалось удалить сессию: {rm_err}")

    journal = session_path + "-journal"
    if os.path.exists(journal):
        try:
            os.remove(journal)
            logger.info("Журнал сессии удалён.")
        except Exception as j_err:
            logger.error(f"Не удалось удалить журнал сессии: {j_err}")


async def _clear_userbot_config():
    """
    Сбрасывает поля USERBOT в конфиге.
    """
    config = await get_valid_config()
    config["USERBOT"] = {
        "API_ID": None,
        "API_HASH": None,
        "PHONE": None,
        "USER_ID": None,
        "USERNAME": None,
        "FIRST_NAME": None,
        "BALANCE": 0,
        "ENABLED": False,
        "CONFIG_ID": None,
        "UPDATE_INTERVAL": 45
    }
    await save_config(config)
    logger.info("Данные в конфиге очищены.")


async def create_userbot_client(
        session_name: str,
        api_id: int,
        api_hash: str,
        phone: str,
        workdir: str,
) -> Client:
    """
    Создаёт экземпляр Pyrogram Client с предустановленными параметрами для отправителя.
    Если CONFIG_ID == None, генерирует случайный CONFIG_ID.
    """
    config = await get_valid_config()
    config_id = config["USERBOT"].get("CONFIG_ID")

    if config_id is None:
        config_id = random.randint(0, len(DEVICE_MODELS) - 1)
        config["USERBOT"]["CONFIG_ID"] = config_id
        await save_config(config)

    return Client(
        name=session_name,
        api_id=api_id,
        api_hash=api_hash,
        phone_number=phone,
        workdir=workdir,
        device_model=DEVICE_MODELS[config_id],
        system_version=SYSTEM_VERSIONS[config_id],
        app_version=APP_VERSIONS[config_id],
        sleep_threshold=30,
        lang_code="en",
        no_updates=True,
        skip_updates=True
    )


async def start_userbot(message: Message, state) -> bool:
    """
    Инициирует подключение отправителя: отправляет код подтверждения и сохраняет состояние клиента.
    """
    global _userbot_client, _current_user_id

    # Запрет интерактивного ввода
    builtins.input = lambda _: (_ for _ in ()).throw(RuntimeError())

    data = await state.get_data()
    user_id = message.from_user.id

    session_name = f"userbot_{user_id}"

    api_id = data["api_id"]
    api_hash = data["api_hash"]
    phone_number = data["phone"]

    app: Client = await create_userbot_client(session_name, api_id, api_hash, phone_number, sessions_dir)

    await app.connect()

    try:
        sent = await app.send_code(phone_number)

        # Сохраняем клиент для дальнейшего использования
        _userbot_client = app
        _current_user_id = user_id
        await state.update_data(phone_code_hash=sent.phone_code_hash, phone=phone_number)

        return True
    except ApiIdInvalid:
        logger.error("Неверный api_id и api_hash. Проверьте данные.")
        await message.answer("🚫 Неверный api_id и api_hash. Проверьте данные.")
        return False
    except PhoneNumberInvalid:
        logger.error("Неверный номер телефона.")
        await message.answer("🚫 Неверный номер телефона.")
        return False
    except FloodWait as e:
        logger.error(f"Слишком много запросов. Подождите {e.value} секунд.")
        await message.answer(f"🚫 Слишком много запросов. Подождите {e.value} секунд.")
        return False
    except BadRequest as e:
        logger.warning(f"Неверный номер телефона или запрос: {e}")
        await message.answer("🚫 Не удалось отправить код. Проверьте номер.")
        return False
    except SecurityCheckMismatch as e:
        logger.error(f"SecurityCheckMismatch: {e}")
        await message.answer("🚫 Ошибка безопасности. Попробуйте позже.")
        return False
    except RPCError as e:
        logger.error(f"Ошибка Telegram API: {e.MESSAGE}")
        await message.answer(f"🚫 Ошибка Telegram API: {e.MESSAGE}")
        return False
    except Exception as e:
        logger.error(f"Неизвестная ошибка: {e}")
        await message.answer(f"🚫 Неизвестная ошибка: {e}")
        return False
    finally:
        if not app.is_connected:
            await app.disconnect()
            return False


async def continue_userbot_signin(call: CallbackQuery, state: FSMContext) -> tuple[bool, bool, bool]:
    """
    Продолжает авторизацию отправителя с использованием кода подтверждения.
    Сохраняет данные аккаунта в конфиг для отображения отправителя.
    """
    global _userbot_client, _userbot_started, _current_user_id

    data = await state.get_data()
    message: Message = call.message
    user_id = call.from_user.id
    code = data["code"]
    attempts = data.get("code_attempts", 0)

    if not _userbot_client:
        logger.error("Клиент не найден. Попробуйте сначала.")
        await message.answer("🚫 Клиент не найден. Попробуйте сначала.")
        return False, False, False

    phone = data["phone"]
    phone_code_hash = data["phone_code_hash"]
    api_id = data["api_id"]
    api_hash = data["api_hash"]

    if not code:
        logger.error("Код не указан.")
        await message.answer("🚫 Код не указан.")
        return False, False, False

    try:
        await _userbot_client.sign_in(
            phone_number=phone,
            phone_code_hash=phone_code_hash,
            phone_code=code
        )

        # Проверка авторизации через get_me()
        try:
            me = await _userbot_client.get_me()
        except Exception as get_me_error:
            logger.error(f"Сессия не авторизована: {get_me_error}")
            await message.answer("🚫 Сессия не авторизована.")
            return False, False, False

        logger.info(f"Отправитель успешно авторизован: {me.first_name} ({me.id})")

        # Устанавливаем статус
        _userbot_started = True
        _current_user_id = user_id

        # Сохраняем данные аккаунта в конфиг для отображения отправителя
        config = await get_valid_config()
        config["USERBOT"]["API_ID"] = api_id
        config["USERBOT"]["API_HASH"] = api_hash
        config["USERBOT"]["PHONE"] = phone
        config["USERBOT"]["USER_ID"] = me.id
        config["USERBOT"]["USERNAME"] = me.username
        config["USERBOT"]["FIRST_NAME"] = me.first_name or "Не указано"
        config["USERBOT"]["ENABLED"] = True
        await save_config(config)

        return True, False, False  # Успешно, пароль не требуется, не retry
    except PhoneCodeInvalid:
        attempts += 1
        await state.update_data(code_attempts=attempts)
        if attempts < 3:
            logger.error(f"Неверный код ({attempts}/3). Попробуйте снова.")
            await message.answer(f"🚫 Неверный код ({attempts}/3). Попробуйте снова.\n\n/cancel — отмена")
            return False, False, True  # retry
        else:
            logger.error("Превышено количество попыток ввода кода.")
            await message.answer("🚫 Превышено количество попыток ввода кода.")
            return False, False, False  # окончательная ошибка
    except SessionPasswordNeeded:
        logger.info(f"Требуется облачный пароль.")
        return True, True, False  # Успешно, но нужен пароль
    except SecurityCheckMismatch as e:
        logger.error(f"SecurityCheckMismatch: {e}")
        await message.answer("🚫 Ошибка безопасности. Попробуйте позже.")
        return False, False, False
    except Exception as e:
        logger.error(f"Ошибка авторизации: {e}")
        await message.answer(f"🚫 Ошибка авторизации: {e}")
        return False, False, False


async def finish_userbot_signin(message: Message, state) -> tuple[bool, bool]:
    """
    Завершает авторизацию отправителя после ввода пароля.
    Сохраняет данные аккаунта в конфиг для отображения отправителя.
    """
    global _userbot_client, _userbot_started, _current_user_id

    data = await state.get_data()
    user_id = message.from_user.id

    if not _userbot_client:
        logger.error("Клиент не найден. Попробуйте сначала.")
        await message.answer("🚫 Клиент не найден. Попробуйте сначала.")
        return False, False

    password = data["password"]
    api_id = data["api_id"]
    api_hash = data["api_hash"]
    phone = data["phone"]
    attempts = data.get("password_attempts", 0)

    if not password:
        logger.error("Пароль не указан.")
        await message.answer("🚫 Пароль не указан.")
        return False, False

    try:
        await _userbot_client.check_password(password)

        # Проверка авторизации через get_me()
        try:
            me = await _userbot_client.get_me()
        except Exception as get_me_error:
            logger.error(f"Сессия не авторизована даже после пароля: {get_me_error}")
            await message.answer("🚫 Сессия не авторизована даже после пароля.")
            return False, False

        logger.info(f"Отправитель успешно авторизован: {me.first_name} ({me.id})")

        # Устанавливаем статус
        _userbot_started = True
        _current_user_id = user_id

        # Сохраняем данные аккаунта в конфиг для отображения отправителя
        config = await get_valid_config()
        config["USERBOT"]["API_ID"] = api_id
        config["USERBOT"]["API_HASH"] = api_hash
        config["USERBOT"]["PHONE"] = phone
        config["USERBOT"]["USER_ID"] = me.id
        config["USERBOT"]["USERNAME"] = me.username
        config["USERBOT"]["FIRST_NAME"] = me.first_name or "Не указано"
        config["USERBOT"]["ENABLED"] = True
        await save_config(config)
        return True, False
    except PasswordHashInvalid:
        attempts += 1
        await state.update_data(password_attempts=attempts)
        if attempts < 3:
            logger.error(f"Неверный пароль ({attempts}/3). Попробуйте снова.")
            await message.answer(f"🚫 Неверный пароль ({attempts}/3). Попробуйте снова.\n\n/cancel — отмена")
            return False, True  # retry
        else:
            logger.error("Превышено количество попыток ввода пароля.")
            await message.answer("🚫 Превышено количество попыток ввода пароля.")
            return False, False  # окончательная ошибка
    except SecurityCheckMismatch as e:
        logger.error(f"SecurityCheckMismatch: {e}")
        await message.answer("🚫 Ошибка безопасности. Попробуйте позже.")
        return False, False
    except Exception as e:
        logger.error(f"Ошибка при вводе пароля: {e}")
        await message.answer(f"🚫 Ошибка при вводе пароля: {e}")
        return False, False


async def userbot_send_self(user_id: int, text: str) -> bool:
    """
    Отправляет подтверждающее сообщение в «Избранное» пользователя от имени отправителя.
    """
    global _userbot_client

    if not is_userbot_active(user_id) or _userbot_client is None:
        logger.error("Клиент не активен.")
        return False

    try:
        await _userbot_client.send_message("me", text, parse_mode=None)
        return True
    except Exception as e:
        logger.error(f"Ошибка при отправке сообщения: {e}")
        return False


async def get_userbot_client(user_id: int) -> Client | None:
    """
    Возвращает объект Pyrogram Client для user_id, если он есть.
    """
    global _userbot_client

    if not is_userbot_active(user_id):
        logger.error("Клиент не активен.")
        return None

    return _userbot_client


async def delete_userbot_session(call: CallbackQuery, user_id: int) -> bool:
    """
    Полностью удаляет отправитель-сессию: останавливает клиента, удаляет файлы и очищает конфиг.
    """
    global _userbot_client, _userbot_started, _current_user_id

    session_name = f"userbot_{user_id}"
    session_path = os.path.join(sessions_dir, f"{session_name}.session")

    # Останавливаем клиент если активен
    if _userbot_client and _userbot_started:
        try:
            await _userbot_client.stop()
            logger.info("Клиент остановлен.")
        except Exception as e:
            logger.error(f"Ошибка при остановке клиента: {e}")

    # Очищаем глобальные переменные
    _userbot_client = None
    _userbot_started = False
    _current_user_id = None

    # Удаляем файлы сессии
    _cleanup_session_files(session_path)

    # Очищаем конфиг
    await _clear_userbot_config()

    await call.message.answer("✅ Отправитель удалён. Можете подключить новый аккаунт.")

    return True


async def get_userbot_stars_balance() -> int:
    """
    Получает баланс звёзд через авторизованного отправителя.
    """
    global _userbot_client, _userbot_started

    if not _userbot_client or not _userbot_started:
        logger.error("Отправитель не активен или не авторизован.")
        return 0

    try:
        stars = await _userbot_client.get_stars_balance()
        return int(stars)  # Явное приведение к int
    except Exception as e:
        logger.error(f"Ошибка при получении баланса отправителя: {e}")
        return 0