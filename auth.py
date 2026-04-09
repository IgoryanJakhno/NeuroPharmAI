# auth.py (улучшенная версия)
import sqlite3
import hashlib
import os
import re
import secrets
from datetime import datetime, timedelta
from typing import Optional, Tuple, List, Dict, Any
import logging
import stat  # Для установки прав на файл


class DatabaseManager:
    """Менеджер для работы с базой данных SQLite"""

    def __init__(self, db_path: str = "neuro_pharm.db"):
        self.db_path = db_path
        self.connection: Optional[sqlite3.Connection] = None
        self.cursor: Optional[sqlite3.Cursor] = None
        self.logger = logging.getLogger(__name__)

    def connect(self) -> bool:
        """Установка соединения с базой данных"""
        try:
            # Проверяем существование файла
            db_exists = os.path.exists(self.db_path)

            self.connection = sqlite3.connect(self.db_path)
            self.connection.row_factory = sqlite3.Row
            self.cursor = self.connection.cursor()

            # Устанавливаем права доступа к файлу БД (только владелец)
            if not db_exists or self._check_permissions():
                self._set_secure_permissions()

            self.logger.info(f"Подключение к БД {self.db_path} установлено")
            return True
        except sqlite3.Error as e:
            self.logger.error(f"Ошибка подключения к БД: {e}")
            return False

    def _set_secure_permissions(self) -> None:
        """Установка безопасных прав на файл БД"""
        try:
            if os.name == 'posix':  # Linux/Mac
                os.chmod(self.db_path, stat.S_IRUSR | stat.S_IWUSR)  # 600
            elif os.name == 'nt':  # Windows
                # В Windows используем icacls для ограничения доступа
                os.system(f'icacls "{self.db_path}" /inheritance:r /grant:r "%USERNAME%:(R,W)"')
        except Exception as e:
            self.logger.warning(f"Не удалось установить права на файл БД: {e}")

    def _check_permissions(self) -> bool:
        """Проверка, не слишком ли открыты права доступа"""
        try:
            if os.name == 'posix':
                mode = os.stat(self.db_path).st_mode
                # Проверяем, что нет прав для группы и других
                return (mode & 0o077) == 0
            return True
        except:
            return False

    def disconnect(self) -> None:
        """Закрытие соединения с базой данных"""
        if self.connection:
            self.connection.close()
            self.connection = None
            self.cursor = None
            self.logger.info("Соединение с БД закрыто")

    def execute_query(self, query: str, params: Tuple = ()) -> bool:
        """Выполнение произвольного SQL-запроса с защитой от инъекций"""
        try:
            self.cursor.execute(query, params)
            self.connection.commit()
            return True
        except sqlite3.Error as e:
            self.logger.error(f"Ошибка выполнения запроса: {e}")
            return False

    def fetch_all(self, query: str, params: Tuple = ()) -> List[Dict[str, Any]]:
        """Получение всех записей по запросу"""
        try:
            self.cursor.execute(query, params)
            rows = self.cursor.fetchall()
            return [dict(row) for row in rows]
        except sqlite3.Error as e:
            self.logger.error(f"Ошибка получения данных: {e}")
            return []

    def fetch_one(self, query: str, params: Tuple = ()) -> Optional[Dict[str, Any]]:
        """Получение одной записи по запросу"""
        try:
            self.cursor.execute(query, params)
            row = self.cursor.fetchone()
            return dict(row) if row else None
        except sqlite3.Error as e:
            self.logger.error(f"Ошибка получения данных: {e}")
            return None

    def get_table_update_date(self, table_name: str) -> Optional[str]:
        """Получение даты последнего обновления таблицы"""
        query = """
        SELECT MAX(
            CASE 
                WHEN sql LIKE '%UpdatedAt%' THEN UpdatedAt 
                ELSE NULL 
            END
        ) as last_update 
        FROM ? 
        LIMIT 1
        """
        result = self.fetch_one(query, (table_name,))
        return result.get('last_update') if result else None


class Authenticator:
    """Класс аутентификации пользователей"""

    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
        self.logger = logging.getLogger(__name__)
        self.password_min_length = 8
        self.password_max_length = 20
        self.login_min_length = 3
        self.login_max_length = 20
        self.password_expiry_days = 180  # 6 месяцев
        self.max_login_attempts = 5  # Максимум попыток входа
        self.lockout_duration = 15  # Минут блокировки

    def initialize_database(self) -> bool:
        """Создание структуры БД при первом запуске"""
        create_users_table = """
        CREATE TABLE IF NOT EXISTS users (
            ID INTEGER PRIMARY KEY AUTOINCREMENT,
            Username TEXT UNIQUE NOT NULL,
            Password TEXT NOT NULL,
            Password_Salt TEXT NOT NULL,
            Role TEXT NOT NULL DEFAULT 'user',
            Password_Expiry DATE NOT NULL,
            Last_Login DATETIME,
            Failed_Attempts INTEGER DEFAULT 0,
            Locked_Until DATETIME,
            CreatedAt DATETIME DEFAULT CURRENT_TIMESTAMP,
            CHECK (Role IN ('user', 'senior', 'dev'))
        )
        """

        create_login_history = """
        CREATE TABLE IF NOT EXISTS login_history (
            ID INTEGER PRIMARY KEY AUTOINCREMENT,
            UserID INTEGER,
            LoginTime DATETIME DEFAULT CURRENT_TIMESTAMP,
            Success BOOLEAN NOT NULL,
            IP_Address TEXT,
            FOREIGN KEY (UserID) REFERENCES users(ID)
        )
        """

        try:
            if not self.db_manager.execute_query(create_users_table):
                return False

            if not self.db_manager.execute_query(create_login_history):
                return False

            # Создаем администратора по умолчанию, если таблица пуста
            users = self.db_manager.fetch_all("SELECT COUNT(*) as count FROM users")
            if users and users[0]['count'] == 0:
                self.create_default_admin()

            self.logger.info("База данных инициализирована успешно")
            return True

        except Exception as e:
            self.logger.error(f"Ошибка инициализации БД: {e}")
            return False

    def create_default_admin(self) -> bool:
        """Создание учетной записи разработчика по умолчанию"""
        default_login = "admin"
        default_password = "Admin12345"  # Пользователь должен сменить при первом входе

        # Генерируем соль и хешируем пароль
        salt = self.generate_salt()
        hashed_password = self.hash_password_with_salt(default_password, salt)

        # Устанавливаем дату истечения (сегодня, чтобы заставить сменить пароль)
        expiry_date = datetime.now().date().isoformat()

        query = """
        INSERT INTO users (Username, Password, Password_Salt, Role, Password_Expiry)
        VALUES (?, ?, ?, 'dev', ?)
        """

        return self.db_manager.execute_query(query, (default_login, hashed_password, salt, expiry_date))

    def generate_salt(self) -> str:
        """Генерация случайной соли"""
        return secrets.token_hex(16)

    def hash_password_with_salt(self, password: str, salt: str) -> str:
        """Хеширование пароля с солью используя PBKDF2"""
        # Используем PBKDF2 с 100000 итераций (рекомендуется OWASP)
        return hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            salt.encode('utf-8'),
            100000
        ).hex()

    def hash_password(self, password: str) -> Tuple[str, str]:
        """
        Хеширование пароля с генерацией новой соли
        Возвращает (хеш, соль)
        """
        salt = self.generate_salt()
        password_hash = self.hash_password_with_salt(password, salt)
        return password_hash, salt

    def verify_password(self, password: str, password_hash: str, salt: str) -> bool:
        """Проверка соответствия пароля хешу с солью"""
        try:
            computed_hash = self.hash_password_with_salt(password, salt)
            # Используем сравнение с постоянным временем для защиты от timing атак
            return secrets.compare_digest(computed_hash, password_hash)
        except Exception:
            return False

    def validate_login(self, login: str) -> Tuple[bool, str]:
        """
        Проверка логина на соответствие требованиям
        Возвращает (валидность, сообщение об ошибке)
        """
        if not login:
            return False, "Логин не может быть пустым"

        if len(login) < self.login_min_length:
            return False, f"Логин должен быть не менее {self.login_min_length} символов"

        if len(login) > self.login_max_length:
            return False, f"Логин не может превышать {self.login_max_length} символов"

        # Проверка на допустимые символы (только латиница и цифры)
        if not re.match(r'^[a-zA-Z0-9]+$', login):
            return False, "Некорректно введен логин. Допустимы только латинские буквы и цифры"

        return True, ""

    def validate_password(self, password: str) -> Tuple[bool, str]:
        """
        Проверка пароля на соответствие требованиям
        Возвращает (валидность, сообщение об ошибке)
        """
        if not password:
            return False, "Пароль не может быть пустым"

        if len(password) < self.password_min_length:
            return False, f"Пароль должен быть не менее {self.password_min_length} символов"

        if len(password) > self.password_max_length:
            return False, f"Пароль не может превышать {self.password_max_length} символов"

        return True, ""

    def check_password_expiry(self, username: str) -> Tuple[bool, Optional[str]]:
        """
        Проверка срока действия пароля
        Возвращает (истек ли срок, сообщение)
        """
        query = "SELECT Password_Expiry FROM users WHERE Username = ?"
        user = self.db_manager.fetch_one(query, (username,))

        if not user:
            return False, None

        expiry_date = datetime.strptime(user['Password_Expiry'], '%Y-%m-%d').date()
        days_left = (expiry_date - datetime.now().date()).days

        if days_left < 0:
            return True, "Срок действия пароля истек. Необходимо сменить пароль"
        elif days_left <= 14:
            return False, f"Срок действия пароля истекает через {days_left} дней. Рекомендуется сменить пароль"

        return False, None

    def authenticate(self, login: str, password: str, ip_address: str = None) -> Tuple[
        bool, Optional[Dict[str, Any]], str]:
        """
        Полная аутентификация пользователя
        Возвращает (успех, данные пользователя, сообщение)
        """
        # Валидация логина
        is_valid, error_msg = self.validate_login(login)
        if not is_valid:
            return False, None, error_msg

        # Валидация пароля
        is_valid, error_msg = self.validate_password(password)
        if not is_valid:
            return False, None, error_msg

        # Поиск пользователя
        query = """
        SELECT ID, Username, Password, Password_Salt, Role, Password_Expiry, 
               Last_Login, Failed_Attempts, Locked_Until
        FROM users 
        WHERE Username = ?
        """
        user = self.db_manager.fetch_one(query, (login,))

        if not user:
            self.log_attempt(None, False, ip_address)
            # Защита от перебора - искусственная задержка
            self._delay_response()
            return False, None, "Неверный логин или пароль"

        # Проверка блокировки аккаунта
        if user['Locked_Until']:
            locked_until = datetime.fromisoformat(user['Locked_Until'])
            if datetime.now() < locked_until:
                minutes_left = (locked_until - datetime.now()).seconds // 60
                return False, None, f"Аккаунт заблокирован. Попробуйте через {minutes_left} минут"

        # Проверка пароля
        if not self.verify_password(password, user['Password'], user['Password_Salt']):
            self._handle_failed_attempt(user['ID'])
            self.log_attempt(user['ID'], False, ip_address)
            self._delay_response()
            return False, None, "Неверный логин или пароль"

        # Сброс счетчика неудачных попыток при успешном входе
        self._reset_failed_attempts(user['ID'])

        # Проверка срока действия пароля
        is_expired, expiry_msg = self.check_password_expiry(login)

        # Обновление даты последнего входа
        update_query = "UPDATE users SET Last_Login = CURRENT_TIMESTAMP WHERE ID = ?"
        self.db_manager.execute_query(update_query, (user['ID'],))

        # Логирование успешного входа
        self.log_attempt(user['ID'], True, ip_address)

        # Удаляем чувствительные данные из возвращаемого объекта
        user_data = {
            'ID': user['ID'],
            'Username': user['Username'],
            'Role': user['Role'],
            'Password_Expiry': user['Password_Expiry'],
            'Last_Login': user['Last_Login']
        }

        if is_expired:
            return True, user_data, expiry_msg
        else:
            return True, user_data, "Аутентификация успешна"

    def _handle_failed_attempt(self, user_id: int) -> None:
        """Обработка неудачной попытки входа"""
        query = """
        UPDATE users 
        SET Failed_Attempts = Failed_Attempts + 1,
            Locked_Until = CASE 
                WHEN Failed_Attempts + 1 >= ? THEN datetime('now', '+' || ? || ' minutes')
                ELSE Locked_Until
            END
        WHERE ID = ?
        """
        self.db_manager.execute_query(query, (self.max_login_attempts, self.lockout_duration, user_id))

    def _reset_failed_attempts(self, user_id: int) -> None:
        """Сброс счетчика неудачных попыток"""
        query = "UPDATE users SET Failed_Attempts = 0, Locked_Until = NULL WHERE ID = ?"
        self.db_manager.execute_query(query, (user_id,))

    def _delay_response(self) -> None:
        """Искусственная задержка для защиты от перебора"""
        import time
        time.sleep(1)  # Задержка 1 секунда

    def log_attempt(self, user_id: Optional[int], success: bool, ip_address: str = None) -> None:
        """Логирование попытки входа"""
        query = """
        INSERT INTO login_history (UserID, Success, IP_Address)
        VALUES (?, ?, ?)
        """
        self.db_manager.execute_query(query, (user_id, success, ip_address))

    def change_password(self, user_id: int, old_password: str, new_password: str) -> Tuple[bool, str]:
        """Смена пароля пользователем"""
        # Получаем текущие данные
        query = "SELECT Password, Password_Salt FROM users WHERE ID = ?"
        user = self.db_manager.fetch_one(query, (user_id,))

        if not user:
            return False, "Пользователь не найден"

        # Проверяем старый пароль
        if not self.verify_password(old_password, user['Password'], user['Password_Salt']):
            return False, "Неверный текущий пароль"

        # Валидируем новый пароль
        is_valid, error_msg = self.validate_password(new_password)
        if not is_valid:
            return False, error_msg

        # Генерируем новую соль и хеш
        new_salt = self.generate_salt()
        new_hash = self.hash_password_with_salt(new_password, new_salt)

        # Устанавливаем новую дату истечения (через 6 месяцев)
        new_expiry = (datetime.now() + timedelta(days=self.password_expiry_days)).date().isoformat()

        # Обновляем пароль
        update_query = """
        UPDATE users 
        SET Password = ?, Password_Salt = ?, Password_Expiry = ?
        WHERE ID = ?
        """

        if self.db_manager.execute_query(update_query, (new_hash, new_salt, new_expiry, user_id)):
            return True, "Пароль успешно изменен"
        else:
            return False, "Ошибка при изменении пароля"

    def reset_password(self, admin_id: int, target_user_id: int, new_password: str) -> Tuple[bool, str]:
        """Сброс пароля администратором (только для роли 'dev')"""
        # Проверяем роль администратора
        admin_query = "SELECT Role FROM users WHERE ID = ?"
        admin = self.db_manager.fetch_one(admin_query, (admin_id,))

        if not admin or admin['Role'] != 'dev':
            return False, "Недостаточно прав для сброса пароля"

        # Валидируем новый пароль
        is_valid, error_msg = self.validate_password(new_password)
        if not is_valid:
            return False, error_msg

        # Генерируем новую соль и хеш
        new_salt = self.generate_salt()
        new_hash = self.hash_password_with_salt(new_password, new_salt)

        # Устанавливаем дату истечения (сегодня, чтобы заставить сменить пароль)
        new_expiry = datetime.now().date().isoformat()

        # Обновляем пароль
        update_query = """
        UPDATE users 
        SET Password = ?, Password_Salt = ?, Password_Expiry = ?, Failed_Attempts = 0, Locked_Until = NULL
        WHERE ID = ?
        """

        if self.db_manager.execute_query(update_query, (new_hash, new_salt, new_expiry, target_user_id)):
            return True, "Пароль успешно сброшен"
        else:
            return False, "Ошибка при сбросе пароля"


# Пример использования модуля
if __name__ == "__main__":
    # Настройка логирования
    logging.basicConfig(level=logging.INFO)

    # Инициализация менеджера БД
    db_mgr = DatabaseManager("neuro_pharm.db")
    if not db_mgr.connect():
        print("Ошибка подключения к БД")
        exit(1)

    # Инициализация аутентификатора
    auth = Authenticator(db_mgr)

    # Создание таблиц при первом запуске
    if not auth.initialize_database():
        print("Ошибка инициализации БД")
        exit(1)

    # Тестирование аутентификации
    print("=== Тестирование модуля аутентификации ===")

    # Попытка входа с учетной записью по умолчанию
    success, user_data, message = auth.authenticate("admin", "Admin12345")
    if success:
        print(f"Вход выполнен: {message}")
        print(f"Пользователь: {user_data['Username']}, Роль: {user_data['Role']}")
    else:
        print(f"Ошибка входа: {message}")

    db_mgr.disconnect()