# services/userbot.py
"""
Модуль управления отправитель-сессией через Pyrogram (упрощенная версия).

Этот модуль содержит функции для:
- Создания, запуска и авторизации отправитель-сессии.
- Управления сессионным файлом и конфигурацией отправителя.
- Получения баланса звёзд через отправитель.

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
    """
    global _userbot_client, _userbot_started, _current_user_id
    is_active = (_userbot_client is not None and
                 _userbot_started and
                 _current_user_id is not None and
                 _current_user_id == user_id)

    logger.debug(
        f"📤 ОТПРАВИТЕЛЬ: Проверка активности для пользователя {user_id}: {'✅ Активен' if is_active else '❌ Неактивен'}")
    return is_active


async def is_userbot_premium(user_id: int) -> bool:
    """
    Проверяет наличие премиум подписки отправитель-сессии.
    """
    global _userbot_client
    if not is_userbot_active(user_id) or _userbot_client is None:
        logger.debug("📤 ОТПРАВИТЕЛЬ: Невозможно проверить премиум статус - отправитель неактивен")
        return False

    try:
        logger.debug("📤 ОТПРАВИТЕЛЬ: Проверка премиум статуса")
        me = await _userbot_client.get_me()
        is_premium = me.is_premium
        logger.debug(f"📤 ОТПРАВИТЕЛЬ: Премиум статус: {'✅ Есть' if is_premium else '❌ Нет'}")
        return is_premium
    except Exception as e:
        logger.error(f"❌ ОТПРАВИТЕЛЬ: Ошибка при проверке премиум статуса: {e}")
        return False


async def try_start_userbot_from_config(user_id: int, bot_id: int) -> bool:
    """
    Проверяет, есть ли валидная отправитель-сессия для пользователя, и запускает её.
    Сохраняет имя аккаунта в конфиг для отображения отправителя.

    :param user_id: ID пользователя Telegram
    :param bot_id: ID бота (для совместимости)
    :return: True если сессия успешно запущена
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
            logger.debug(
                "📤 ОТПРАВИТЕЛЬ: Это нормально для первого запуска - пользователь может настроить отправитель через бот")
            _cleanup_session_files(session_path)
            await _clear_userbot_config()
            return False

        api_id = userbot_data["API_ID"]
        api_hash = userbot_data["API_HASH"]
        phone_number = userbot_data["PHONE"]

        app: Client = await create_userbot_client(session_name, api_id, api_hash, phone_number, sessions_dir)

        if os.path.exists(session_path):
            logger.debug(f"📤 ОТПРАВИТЕЛЬ: Найден файл сессии: {session_path}")

            file_size = os.path.getsize(session_path)
            if file_size < 100:
                logger.warning(f"⚠️ ОТПРАВИТЕЛЬ: Файл сессии подозрительно мал ({file_size} байт) - возможно поврежден")

            try:
                logger.info("📤 ОТПРАВИТЕЛЬ: Попытка запуска существующей сессии")
                await app.start()
                me = await app.get_me()

                logger.info(
                    f"✅ ОТПРАВИТЕЛЬ: Успешная авторизация как {me.first_name} (@{me.username or 'без username'}) ID: {me.id}")

                # Сохраняем данные аккаунта в конфиг для отображения отправителя
                config["USERBOT"]["USER_ID"] = me.id
                config["USERBOT"]["USERNAME"] = me.username
                config["USERBOT"]["FIRST_NAME"] = me.first_name or "Не указано"
                await save_config(config)
                logger.debug("📤 ОТПРАВИТЕЛЬ: Данные аккаунта сохранены в конфиг")

                # Устанавливаем глобальные переменные
                _userbot_client = app
                _userbot_started = True
                _current_user_id = user_id

                logger.info("🟢 ОТПРАВИТЕЛЬ: Отправитель успешно запущен и готов к работе")
                return True

            except Exception as e:
                logger.error(f"❌ ОТПРАВИТЕЛЬ: Сессия повреждена или не завершена: {e}")
                try:
                    await app.stop()
                    logger.debug("📤 ОТПРАВИТЕЛЬ: Поврежденный клиент остановлен")
                except Exception as stop_err:
                    logger.error(f"❌ ОТПРАВИТЕЛЬ: Не удалось остановить поврежденный клиент: {stop_err}")

                logger.info("🗑️ ОТПРАВИТЕЛЬ: Удаление поврежденных файлов сессии")
                _cleanup_session_files(session_path)

        else:
            logger.debug("📤 ОТПРАВИТЕЛЬ: Файл сессии не найден - требуется первичная авторизация")

        # Очистка USERBOT из конфига при отсутствии или повреждении сессии
        logger.debug("📤 ОТПРАВИТЕЛЬ: Очистка данных отправителя в конфиге")
        await _clear_userbot_config()
        return False

    except Exception as e:
        logger.error(f"💥 ОТПРАВИТЕЛЬ: Критическая ошибка при запуске отправителя: {e}")
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
    """
    Сбрасывает поля USERBOT в конфиге.
    """
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
        "ENABLED": False,
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

    logger.debug(
        f"📤 ОТПРАВИТЕЛЬ: Параметры клиента - Устройство: {DEVICE_MODEL}, Система: {SYSTEM_VERSION}, Приложение: {APP_VERSION}")

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


async def start_userbot(message: Message, state) -> bool:
    """
    Инициирует подключение отправителя: отправляет код подтверждения и сохраняет состояние клиента.

    :param message: Сообщение пользователя
    :param state: FSM состояние
    :return: True если код успешно отправлен
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

    logger.debug("📤 ОТПРАВИТЕЛЬ: Подключение к Telegram")
    await app.connect()

    try:
        sent = await app.send_code(phone_number)

        # Сохраняем клиент для дальнейшего использования
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
    except BadRequest as e:
        logger.warning(f"⚠️ ОТПРАВИТЕЛЬ: Неверный номер телефона или запрос: {e}")
        await message.answer("🚫 Не удалось отправить код. Проверьте номер.")
        return False
    except SecurityCheckMismatch as e:
        logger.error(f"❌ ОТПРАВИТЕЛЬ: Ошибка безопасности: {e}")
        await message.answer("🚫 Ошибка безопасности. Попробуйте позже.")
        return False
    except RPCError as e:
        logger.error(f"❌ ОТПРАВИТЕЛЬ: Ошибка Telegram API: {e.MESSAGE}")
        await message.answer(f"🚫 Ошибка Telegram API: {e.MESSAGE}")
        return False
    except Exception as e:
        logger.error(f"💥 ОТПРАВИТЕЛЬ: Неизвестная ошибка при отправке кода: {e}")
        await message.answer(f"🚫 Неизвестная ошибка: {e}")
        return False
    finally:
        if not app.is_connected:
            logger.debug("📤 ОТПРАВИТЕЛЬ: Отключение от Telegram")
            await app.disconnect()
            return False


async def continue_userbot_signin(call: CallbackQuery, state: FSMContext) -> tuple[bool, bool, bool]:
    """
    Продолжает авторизацию отправителя с использованием кода подтверждения.
    Сохраняет данные аккаунта в конфиг для отображения отправителя.

    :param call: Callback query от пользователя
    :param state: FSM состояние
    :return: (success, need_password, retry)
    """
    global _userbot_client, _userbot_started, _current_user_id

    data = await state.get_data()
    user_id = call.from_user.id
    code = data["code"]
    attempts = data.get("code_attempts", 0)

    if not _userbot_client:
        logger.error("❌ ОТПРАВИТЕЛЬ: Клиент не найден - процесс авторизации прерван")
        await call.message.answer("🚫 Клиент не найден. Попробуйте сначала.")
        return False, False, False

    phone = data["phone"]
    phone_code_hash = data["phone_code_hash"]
    api_id = data["api_id"]
    api_hash = data["api_hash"]

    if not code:
        logger.error("❌ ОТПРАВИТЕЛЬ: Код не указан")
        await call.message.answer("🚫 Код не указан.")
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
            logger.error(f"❌ ОТПРАВИТЕЛЬ: Сессия не авторизована после ввода кода: {get_me_error}")
            await call.message.answer("🚫 Сессия не авторизована.")
            return False, False, False

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

        logger.info(
            f"✅ ОТПРАВИТЕЛЬ: Авторизация завершена успешно как {me.first_name} (@{me.username or 'без username'}) ID: {me.id}")

        return True, False, False  # Успешно, пароль не требуется, не retry

    except PhoneCodeInvalid:
        attempts += 1
        await state.update_data(code_attempts=attempts)
        if attempts < 3:
            logger.warning(f"⚠️ ОТПРАВИТЕЛЬ: Неверный код (попытка {attempts}/3)")
            await call.message.answer(f"🚫 Неверный код ({attempts}/3). Попробуйте снова.\n\n/cancel — отмена")
            return False, False, True  # retry
        else:
            logger.error("❌ ОТПРАВИТЕЛЬ: Превышено количество попыток ввода кода")
            await call.message.answer("🚫 Превышено количество попыток ввода кода.")
            return False, False, False  # окончательная ошибка
    except SessionPasswordNeeded:
        logger.info("🔐 ОТПРАВИТЕЛЬ: Требуется облачный пароль для завершения авторизации")
        return True, True, False  # Успешно, но нужен пароль
    except SecurityCheckMismatch as e:
        logger.error(f"❌ ОТПРАВИТЕЛЬ: Ошибка безопасности при проверке кода: {e}")
        await call.message.answer("🚫 Ошибка безопасности. Попробуйте позже.")
        return False, False, False
    except Exception as e:
        logger.error(f"💥 ОТПРАВИТЕЛЬ: Ошибка при проверке кода: {e}")
        await call.message.answer(f"🚫 Ошибка авторизации: {e}")
        return False, False, False


async def finish_userbot_signin(message: Message, state) -> tuple[bool, bool]:
    """
    Завершает авторизацию отправителя после ввода пароля.
    Сохраняет данные аккаунта в конфиг для отображения отправителя.

    :param message: Сообщение пользователя
    :param state: FSM состояние
    :return: (success, retry)
    """
    global _userbot_client, _userbot_started, _current_user_id

    data = await state.get_data()
    user_id = message.from_user.id

    if not _userbot_client:
        logger.error("❌ ОТПРАВИТЕЛЬ: Клиент не найден при проверке пароля")
        await message.answer("🚫 Клиент не найден. Попробуйте сначала.")
        return False, False

    password = data["password"]
    api_id = data["api_id"]
    api_hash = data["api_hash"]
    phone = data["phone"]
    attempts = data.get("password_attempts", 0)

    if not password:
        logger.error("❌ ОТПРАВИТЕЛЬ: Пароль не указан")
        await message.answer("🚫 Пароль не указан.")
        return False, False

    try:
        await _userbot_client.check_password(password)

        # Проверка авторизации через get_me()
        try:
            me = await _userbot_client.get_me()
        except Exception as get_me_error:
            logger.error(f"❌ ОТПРАВИТЕЛЬ: Сессия не авторизована даже после пароля: {get_me_error}")
            await message.answer("🚫 Сессия не авторизована даже после пароля.")
            return False, False

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

        logger.info(
            f"✅ ОТПРАВИТЕЛЬ: Авторизация завершена успешно как {me.first_name} (@{me.username or 'без username'}) ID: {me.id}")

        return True, False

    except PasswordHashInvalid:
        attempts += 1
        await state.update_data(password_attempts=attempts)
        if attempts < 3:
            logger.warning(f"⚠️ ОТПРАВИТЕЛЬ: Неверный пароль (попытка {attempts}/3)")
            await message.answer(f"🚫 Неверный пароль ({attempts}/3). Попробуйте снова.\n\n/cancel — отмена")
            return False, True  # retry
        else:
            logger.error("❌ ОТПРАВИТЕЛЬ: Превышено количество попыток ввода пароля")
            await message.answer("🚫 Превышено количество попыток ввода пароля.")
            return False, False  # окончательная ошибка
    except SecurityCheckMismatch as e:
        logger.error(f"❌ ОТПРАВИТЕЛЬ: Ошибка безопасности при проверке пароля: {e}")
        await message.answer("🚫 Ошибка безопасности. Попробуйте позже.")
        return False, False
    except Exception as e:
        logger.error(f"💥 ОТПРАВИТЕЛЬ: Ошибка при проверке пароля: {e}")
        await message.answer(f"🚫 Ошибка при вводе пароля: {e}")
        return False, False


async def get_userbot_client(user_id: int) -> Client | None:
    """
    Возвращает объект Pyrogram Client для user_id, если он есть.

    :param user_id: ID пользователя
    :return: Pyrogram Client или None
    """
    logger.debug(f"📤 ОТПРАВИТЕЛЬ: Запрос клиента для пользователя {user_id}")

    if not is_userbot_active(user_id):
        logger.debug("❌ ОТПРАВИТЕЛЬ: Клиент недоступен - отправитель неактивен")
        return None

    logger.debug("✅ ОТПРАВИТЕЛЬ: Клиент предоставлен")
    return _userbot_client


async def delete_userbot_session(call: CallbackQuery, user_id: int) -> bool:
    """
    Полностью удаляет отправитель-сессию: останавливает клиента, удаляет файлы и очищает конфиг.

    :param call: Callback query
    :param user_id: ID пользователя
    :return: True если успешно удалено
    """
    global _userbot_client, _userbot_started, _current_user_id

    logger.info(f"🗑️ ОТПРАВИТЕЛЬ: Начало удаления сессии для пользователя {user_id}")

    session_name = f"userbot_{user_id}"
    session_path = os.path.join(sessions_dir, f"{session_name}.session")

    # Останавливаем клиент если активен
    if _userbot_client and _userbot_started:
        try:
            logger.debug("📤 ОТПРАВИТЕЛЬ: Остановка активного клиента")
            await _userbot_client.stop()
            logger.info("✅ ОТПРАВИТЕЛЬ: Клиент успешно остановлен")
        except Exception as e:
            logger.error(f"❌ ОТПРАВИТЕЛЬ: Ошибка при остановке клиента: {e}")

    # Очищаем глобальные переменные
    _userbot_client = None
    _userbot_started = False
    _current_user_id = None
    logger.debug("📤 ОТПРАВИТЕЛЬ: Глобальные переменные очищены")

    # Удаляем файлы сессии
    _cleanup_session_files(session_path)

    # Очищаем конфиг
    await _clear_userbot_config()

    logger.info("✅ ОТПРАВИТЕЛЬ: Сессия полностью удалена")
    await call.message.answer("✅ Отправитель удалён. Можете подключить новый аккаунт.")

    return True


async def get_userbot_stars_balance() -> int:
    """
    Получает баланс звёзд через авторизованного отправителя.

    :return: Баланс в звездах
    """
    global _userbot_client, _userbot_started

    logger.debug("💰 ОТПРАВИТЕЛЬ: Запрос баланса звезд")

    if not _userbot_client or not _userbot_started:
        logger.error("❌ ОТПРАВИТЕЛЬ: Невозможно получить баланс - отправитель не активен или не авторизован")
        return 0

    try:
        stars = await _userbot_client.get_stars_balance()
        balance = int(stars)  # Явное приведение к int
        logger.debug(f"💰 ОТПРАВИТЕЛЬ: Получен баланс: {balance:,} ★")
        return balance
    except Exception as e:
        logger.error(f"❌ ОТПРАВИТЕЛЬ: Ошибка при получении баланса: {e}")
        return 0