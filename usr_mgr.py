# usr_mgr.py
import sqlite3
import re
from datetime import datetime, timedelta
from typing import Optional, Tuple, List, Dict, Any, Callable
import logging
import hashlib
import secrets


class UserManager:
    """
    Класс менеджера пользователей согласно ТЗ п. 4.2.2

    Методы:
    - создание нового пользователя
    - обновление данных о пользователе
    - удаление пользователя
    - получение информации
    - список всех пользователей с возможностью фильтрации
    - сброс пароля
    - обновление срока действия пароля
    """

    def __init__(self, db_manager):
        """
        Инициализация менеджера пользователей

        Args:
            db_manager: Экземпляр DatabaseManager для работы с БД
        """
        self.db_manager = db_manager
        self.logger = logging.getLogger(__name__)
        self.password_min_length = 8
        self.password_max_length = 20
        self.login_min_length = 3
        self.login_max_length = 20
        self.password_expiry_days = 180  # 6 месяцев

    def generate_salt(self) -> str:
        """Генерация случайной соли"""
        return secrets.token_hex(16)

    def hash_password_with_salt(self, password: str, salt: str) -> str:
        """Хеширование пароля с солью используя PBKDF2"""
        return hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            salt.encode('utf-8'),
            100000
        ).hex()

    def validate_login(self, login: str) -> Tuple[bool, str]:
        """
        Проверка логина на соответствие требованиям

        Returns:
            (валидность, сообщение об ошибке)
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

        Returns:
            (валидность, сообщение об ошибке)
        """
        if not password:
            return False, "Пароль не может быть пустым"

        if len(password) < self.password_min_length:
            return False, f"Пароль должен быть не менее {self.password_min_length} символов"

        if len(password) > self.password_max_length:
            return False, f"Пароль не может превышать {self.password_max_length} символов"

        return True, ""

    def validate_role(self, role: str) -> Tuple[bool, str]:
        """
        Проверка роли на допустимость

        Returns:
            (валидность, сообщение об ошибке)
        """
        valid_roles = ['user', 'senior', 'dev']
        if role not in valid_roles:
            return False, f"Недопустимая роль. Допустимые роли: {', '.join(valid_roles)}"
        return True, ""

    def create_user(self, username: str, password: str, role: str = 'user',
                    creator_id: Optional[int] = None) -> Tuple[bool, str, Optional[int]]:
        """
        Создание нового пользователя

        Args:
            username: Имя пользователя
            password: Пароль
            role: Роль (user/senior/dev)
            creator_id: ID пользователя, создающего запись (для аудита)

        Returns:
            (успех, сообщение, ID созданного пользователя)
        """
        # Проверка прав создателя (если указан)
        if creator_id:
            creator = self.get_user_info(creator_id)
            if not creator:
                return False, "Создатель не найден", None

            # Только dev может создавать пользователей с ролью dev или seniour
            if role in ['dev', 'senior'] and creator['Role'] != 'dev':
                return False, "Недостаточно прав для создания пользователя с такой ролью", None

        # Валидация логина
        is_valid, error_msg = self.validate_login(username)
        if not is_valid:
            return False, error_msg, None

        # Проверка уникальности логина
        existing_user = self.db_manager.fetch_one(
            "SELECT ID FROM users WHERE Username = ?",
            (username,)
        )
        if existing_user:
            return False, "Пользователь с таким логином уже существует", None

        # Валидация пароля
        is_valid, error_msg = self.validate_password(password)
        if not is_valid:
            return False, error_msg, None

        # Валидация роли
        is_valid, error_msg = self.validate_role(role)
        if not is_valid:
            return False, error_msg, None

        # Генерация соли и хеша пароля
        salt = self.generate_salt()
        password_hash = self.hash_password_with_salt(password, salt)

        # Установка даты истечения пароля
        expiry_date = (datetime.now() + timedelta(days=self.password_expiry_days)).date().isoformat()

        # Создание пользователя
        query = """
        INSERT INTO users (Username, Password, Password_Salt, Role, Password_Expiry)
        VALUES (?, ?, ?, ?, ?)
        """

        try:
            success = self.db_manager.execute_query(
                query,
                (username, password_hash, salt, role, expiry_date)
            )

            if success:
                # Получаем ID созданного пользователя
                new_user = self.db_manager.fetch_one(
                    "SELECT ID FROM users WHERE Username = ?",
                    (username,)
                )

                if new_user:
                    user_id = new_user['ID']
                    self._log_action(creator_id, 'CREATE_USER', f"Created user {username} with role {role}")
                    self.logger.info(f"Создан новый пользователь: {username} (ID: {user_id})")
                    return True, f"Пользователь {username} успешно создан", user_id

            return False, "Ошибка при создании пользователя", None

        except Exception as e:
            self.logger.error(f"Ошибка создания пользователя {username}: {e}")
            return False, f"Ошибка: {str(e)}", None

    def update_user(self, user_id: int, updater_id: Optional[int] = None,
                    username: Optional[str] = None, role: Optional[str] = None) -> Tuple[bool, str]:
        """
        Обновление данных о пользователе

        Args:
            user_id: ID обновляемого пользователя
            updater_id: ID пользователя, выполняющего обновление
            username: Новое имя пользователя (опционально)
            role: Новая роль (опционально)

        Returns:
            (успех, сообщение)
        """
        # Проверка существования пользователя
        user = self.get_user_info(user_id)
        if not user:
            return False, "Пользователь не найден"

        # Проверка прав обновляющего
        if updater_id:
            updater = self.get_user_info(updater_id)
            if not updater:
                return False, "Обновляющий пользователь не найден"

            # Только dev может менять роли
            if role and updater['Role'] != 'dev':
                return False, "Недостаточно прав для изменения роли"

            # Нельзя изменить роль dev другому пользователю
            if user['Role'] == 'dev' and updater['Role'] != 'dev':
                return False, "Нельзя изменить данные разработчика"

        updates = []
        params = []

        # Обновление имени пользователя
        if username and username != user['Username']:
            is_valid, error_msg = self.validate_login(username)
            if not is_valid:
                return False, error_msg

            # Проверка уникальности
            existing = self.db_manager.fetch_one(
                "SELECT ID FROM users WHERE Username = ? AND ID != ?",
                (username, user_id)
            )
            if existing:
                return False, "Пользователь с таким логином уже существует"

            updates.append("Username = ?")
            params.append(username)

        # Обновление роли
        if role and role != user['Role']:
            is_valid, error_msg = self.validate_role(role)
            if not is_valid:
                return False, error_msg

            updates.append("Role = ?")
            params.append(role)

        if not updates:
            return False, "Нет данных для обновления"

        params.append(user_id)
        query = f"UPDATE users SET {', '.join(updates)} WHERE ID = ?"

        try:
            success = self.db_manager.execute_query(query, tuple(params))

            if success:
                self._log_action(updater_id, 'UPDATE_USER',
                                 f"Updated user ID {user_id}: {', '.join(updates)}")
                self.logger.info(f"Обновлены данные пользователя ID {user_id}")
                return True, "Данные пользователя успешно обновлены"
            else:
                return False, "Ошибка при обновлении данных"

        except Exception as e:
            self.logger.error(f"Ошибка обновления пользователя ID {user_id}: {e}")
            return False, f"Ошибка: {str(e)}"

    def delete_user(self, user_id: int, deleter_id: Optional[int] = None) -> Tuple[bool, str]:
        """
        Удаление пользователя

        Args:
            user_id: ID удаляемого пользователя
            deleter_id: ID пользователя, выполняющего удаление

        Returns:
            (успех, сообщение)
        """
        # Проверка существования пользователя
        user = self.get_user_info(user_id)
        if not user:
            return False, "Пользователь не найден"

        # Защита от удаления последнего разработчика
        if user['Role'] == 'dev':
            dev_count = self.db_manager.fetch_one(
                "SELECT COUNT(*) as count FROM users WHERE Role = 'dev'"
            )
            if dev_count and dev_count['count'] <= 1:
                return False, "Нельзя удалить последнего разработчика системы"

        # Проверка прав удаляющего
        if deleter_id:
            deleter = self.get_user_info(deleter_id)
            if not deleter:
                return False, "Удаляющий пользователь не найден"

            # Только dev может удалять пользователей
            if deleter['Role'] != 'dev':
                return False, "Недостаточно прав для удаления пользователей"

            # Нельзя удалить самого себя
            if deleter_id == user_id:
                return False, "Нельзя удалить самого себя"

        # Сохраняем информацию для логирования
        username = user['Username']
        role = user['Role']

        # Удаление пользователя
        query = "DELETE FROM users WHERE ID = ?"

        try:
            success = self.db_manager.execute_query(query, (user_id,))

            if success:
                self._log_action(deleter_id, 'DELETE_USER',
                                 f"Deleted user {username} (ID: {user_id}, Role: {role})")
                self.logger.info(f"Удален пользователь: {username} (ID: {user_id})")
                return True, f"Пользователь {username} успешно удален"
            else:
                return False, "Ошибка при удалении пользователя"

        except Exception as e:
            self.logger.error(f"Ошибка удаления пользователя ID {user_id}: {e}")
            return False, f"Ошибка: {str(e)}"

    def get_user_info(self, user_id: int) -> Optional[Dict[str, Any]]:
        """
        Получение информации о пользователе

        Args:
            user_id: ID пользователя

        Returns:
            Словарь с информацией о пользователе или None
        """
        query = """
        SELECT ID, Username, Role, Password_Expiry, Last_Login, 
               CreatedAt, Failed_Attempts,
               CASE WHEN Locked_Until > CURRENT_TIMESTAMP THEN 1 ELSE 0 END as Is_Locked
        FROM users 
        WHERE ID = ?
        """

        try:
            user = self.db_manager.fetch_one(query, (user_id,))

            if user:
                # Добавляем дополнительную информацию
                user['Password_Expired'] = self._is_password_expired(user['Password_Expiry'])
                user['Days_Until_Expiry'] = self._days_until_expiry(user['Password_Expiry'])

                # Получаем статистику входов
                stats = self._get_user_login_stats(user_id)
                user.update(stats)

                return user

            return None

        except Exception as e:
            self.logger.error(f"Ошибка получения информации о пользователе ID {user_id}: {e}")
            return None

    def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        """
        Получение информации о пользователе по имени пользователя

        Args:
            username: Имя пользователя

        Returns:
            Словарь с информацией о пользователе или None
        """
        query = "SELECT ID FROM users WHERE Username = ?"

        try:
            user = self.db_manager.fetch_one(query, (username,))
            if user:
                return self.get_user_info(user['ID'])
            return None

        except Exception as e:
            self.logger.error(f"Ошибка поиска пользователя {username}: {e}")
            return None

    def get_all_users(self, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Получение списка всех пользователей с возможностью фильтрации

        Args:
            filters: Словарь с фильтрами:
                - role: Фильтр по роли
                - username_pattern: Поиск по части имени
                - expired_passwords: Только с истекшими паролями (True/False)
                - locked: Только заблокированные (True/False)
                - created_after: Созданные после даты
                - limit: Ограничение количества
                - offset: Смещение для пагинации

        Returns:
            Список пользователей
        """
        query = """
        SELECT ID, Username, Role, Password_Expiry, Last_Login, 
               CreatedAt, Failed_Attempts,
               CASE WHEN Locked_Until > CURRENT_TIMESTAMP THEN 1 ELSE 0 END as Is_Locked
        FROM users 
        WHERE 1=1
        """

        params = []

        if filters:
            # Фильтр по роли
            if 'role' in filters:
                query += " AND Role = ?"
                params.append(filters['role'])

            # Поиск по имени
            if 'username_pattern' in filters:
                query += " AND Username LIKE ?"
                params.append(f"%{filters['username_pattern']}%")

            # Фильтр по истекшим паролям
            if filters.get('expired_passwords'):
                query += " AND Password_Expiry < DATE('now')"

            # Фильтр по заблокированным
            if filters.get('locked'):
                query += " AND Locked_Until > CURRENT_TIMESTAMP"

            # Фильтр по дате создания
            if 'created_after' in filters:
                query += " AND CreatedAt >= ?"
                params.append(filters['created_after'])

        # Сортировка
        query += " ORDER BY Username ASC"

        # Пагинация
        if filters and 'limit' in filters:
            query += " LIMIT ?"
            params.append(filters['limit'])

            if 'offset' in filters:
                query += " OFFSET ?"
                params.append(filters['offset'])

        try:
            users = self.db_manager.fetch_all(query, tuple(params) if params else ())

            # Добавляем дополнительную информацию
            for user in users:
                user['Password_Expired'] = self._is_password_expired(user['Password_Expiry'])
                user['Days_Until_Expiry'] = self._days_until_expiry(user['Password_Expiry'])

            return users

        except Exception as e:
            self.logger.error(f"Ошибка получения списка пользователей: {e}")
            return []

    def reset_password(self, user_id: int, new_password: str,
                       admin_id: Optional[int] = None) -> Tuple[bool, str]:
        """
        Сброс пароля пользователя

        Args:
            user_id: ID пользователя
            new_password: Новый пароль
            admin_id: ID администратора, выполняющего сброс

        Returns:
            (успех, сообщение)
        """
        # Проверка существования пользователя
        user = self.get_user_info(user_id)
        if not user:
            return False, "Пользователь не найден"

        # Проверка прав администратора
        if admin_id:
            admin = self.get_user_info(admin_id)
            if not admin:
                return False, "Администратор не найден"

            # Только dev может сбрасывать пароли
            if admin['Role'] != 'dev':
                return False, "Недостаточно прав для сброса пароля"

        # Валидация нового пароля
        is_valid, error_msg = self.validate_password(new_password)
        if not is_valid:
            return False, error_msg

        # Генерация новой соли и хеша
        new_salt = self.generate_salt()
        new_hash = self.hash_password_with_salt(new_password, new_salt)

        # Устанавливаем дату истечения (сегодня, чтобы заставить сменить)
        new_expiry = datetime.now().date().isoformat()

        # Обновление пароля
        query = """
        UPDATE users 
        SET Password = ?, Password_Salt = ?, Password_Expiry = ?, 
            Failed_Attempts = 0, Locked_Until = NULL
        WHERE ID = ?
        """

        try:
            success = self.db_manager.execute_query(
                query,
                (new_hash, new_salt, new_expiry, user_id)
            )

            if success:
                self._log_action(admin_id, 'RESET_PASSWORD',
                                 f"Reset password for user {user['Username']} (ID: {user_id})")
                self.logger.info(f"Сброшен пароль пользователя ID {user_id}")
                return True, f"Пароль пользователя {user['Username']} успешно сброшен"
            else:
                return False, "Ошибка при сбросе пароля"

        except Exception as e:
            self.logger.error(f"Ошибка сброса пароля для ID {user_id}: {e}")
            return False, f"Ошибка: {str(e)}"

    def update_password_expiry(self, user_id: int, days: Optional[int] = None,
                               admin_id: Optional[int] = None) -> Tuple[bool, str]:
        """
        Обновление срока действия пароля

        Args:
            user_id: ID пользователя
            days: Количество дней до истечения (None = стандартные 180 дней)
            admin_id: ID администратора, выполняющего обновление

        Returns:
            (успех, сообщение)
        """
        # Проверка существования пользователя
        user = self.get_user_info(user_id)
        if not user:
            return False, "Пользователь не найден"

        # Проверка прав администратора
        if admin_id:
            admin = self.get_user_info(admin_id)
            if not admin:
                return False, "Администратор не найден"

            # Только dev может обновлять сроки действия паролей
            if admin['Role'] != 'dev':
                return False, "Недостаточно прав для обновления срока действия пароля"

        # Определяем количество дней
        expiry_days = days if days is not None else self.password_expiry_days

        if expiry_days <= 0:
            return False, "Срок действия должен быть положительным числом"

        # Рассчитываем новую дату истечения
        new_expiry = (datetime.now() + timedelta(days=expiry_days)).date().isoformat()

        # Обновление срока действия
        query = "UPDATE users SET Password_Expiry = ? WHERE ID = ?"

        try:
            success = self.db_manager.execute_query(query, (new_expiry, user_id))

            if success:
                self._log_action(admin_id, 'UPDATE_PASSWORD_EXPIRY',
                                 f"Updated password expiry for user {user['Username']} (ID: {user_id}) to {expiry_days} days")
                self.logger.info(f"Обновлен срок действия пароля для ID {user_id}: {expiry_days} дней")
                return True, f"Срок действия пароля обновлен на {expiry_days} дней"
            else:
                return False, "Ошибка при обновлении срока действия пароля"

        except Exception as e:
            self.logger.error(f"Ошибка обновления срока действия для ID {user_id}: {e}")
            return False, f"Ошибка: {str(e)}"

    def unlock_user(self, user_id: int, admin_id: Optional[int] = None) -> Tuple[bool, str]:
        """
        Разблокировка пользователя

        Args:
            user_id: ID пользователя
            admin_id: ID администратора

        Returns:
            (успех, сообщение)
        """
        # Проверка существования пользователя
        user = self.get_user_info(user_id)
        if not user:
            return False, "Пользователь не найден"

        # Проверка прав администратора
        if admin_id:
            admin = self.get_user_info(admin_id)
            if not admin:
                return False, "Администратор не найден"

            # Только dev или senior может разблокировать
            if admin['Role'] not in ['dev', 'senior']:
                return False, "Недостаточно прав для разблокировки"

        # Разблокировка
        query = "UPDATE users SET Failed_Attempts = 0, Locked_Until = NULL WHERE ID = ?"

        try:
            success = self.db_manager.execute_query(query, (user_id,))

            if success:
                self._log_action(admin_id, 'UNLOCK_USER',
                                 f"Unlocked user {user['Username']} (ID: {user_id})")
                self.logger.info(f"Разблокирован пользователь ID {user_id}")
                return True, f"Пользователь {user['Username']} разблокирован"
            else:
                return False, "Ошибка при разблокировке"

        except Exception as e:
            self.logger.error(f"Ошибка разблокировки ID {user_id}: {e}")
            return False, f"Ошибка: {str(e)}"

    def get_user_statistics(self) -> Dict[str, Any]:
        """
        Получение статистики по пользователям

        Returns:
            Словарь со статистикой
        """
        stats = {}

        try:
            # Общее количество пользователей
            total = self.db_manager.fetch_one("SELECT COUNT(*) as count FROM users")
            stats['total_users'] = total['count'] if total else 0

            # По ролям
            roles = self.db_manager.fetch_all("""
                SELECT Role, COUNT(*) as count 
                FROM users 
                GROUP BY Role
            """)
            stats['by_role'] = {row['Role']: row['count'] for row in roles}

            # Активные пользователи (входили за последние 30 дней)
            active = self.db_manager.fetch_one("""
                SELECT COUNT(*) as count 
                FROM users 
                WHERE Last_Login >= DATE('now', '-30 days')
            """)
            stats['active_users'] = active['count'] if active else 0

            # Пользователи с истекшими паролями
            expired = self.db_manager.fetch_one("""
                SELECT COUNT(*) as count 
                FROM users 
                WHERE Password_Expiry < DATE('now')
            """)
            stats['expired_passwords'] = expired['count'] if expired else 0

            # Заблокированные пользователи
            locked = self.db_manager.fetch_one("""
                SELECT COUNT(*) as count 
                FROM users 
                WHERE Locked_Until > CURRENT_TIMESTAMP
            """)
            stats['locked_users'] = locked['count'] if locked else 0

            return stats

        except Exception as e:
            self.logger.error(f"Ошибка получения статистики: {e}")
            return {}

    def _is_password_expired(self, expiry_date: str) -> bool:
        """Проверка, истек ли срок действия пароля"""
        try:
            expiry = datetime.strptime(expiry_date, '%Y-%m-%d').date()
            return expiry < datetime.now().date()
        except:
            return False

    def _days_until_expiry(self, expiry_date: str) -> int:
        """Количество дней до истечения срока действия пароля"""
        try:
            expiry = datetime.strptime(expiry_date, '%Y-%m-%d').date()
            return (expiry - datetime.now().date()).days
        except:
            return 0

    def _get_user_login_stats(self, user_id: int) -> Dict[str, Any]:
        """Получение статистики входов пользователя"""
        stats = {}

        try:
            # Количество успешных входов
            success = self.db_manager.fetch_one("""
                SELECT COUNT(*) as count 
                FROM login_history 
                WHERE UserID = ? AND Success = 1
            """, (user_id,))
            stats['successful_logins'] = success['count'] if success else 0

            # Количество неудачных попыток
            failed = self.db_manager.fetch_one("""
                SELECT COUNT(*) as count 
                FROM login_history 
                WHERE UserID = ? AND Success = 0
            """, (user_id,))
            stats['failed_logins'] = failed['count'] if failed else 0

            # Последняя попытка входа
            last_attempt = self.db_manager.fetch_one("""
                SELECT LoginTime, Success, IP_Address
                FROM login_history 
                WHERE UserID = ?
                ORDER BY LoginTime DESC
                LIMIT 1
            """, (user_id,))

            if last_attempt:
                stats['last_login_attempt'] = {
                    'time': last_attempt['LoginTime'],
                    'success': bool(last_attempt['Success']),
                    'ip': last_attempt['IP_Address']
                }

            return stats

        except Exception as e:
            self.logger.error(f"Ошибка получения статистики входов: {e}")
            return {}

    def _log_action(self, user_id: Optional[int], action: str, details: str) -> None:
        """
        Логирование действий с пользователями

        Args:
            user_id: ID пользователя, выполнившего действие
            action: Тип действия
            details: Детали действия
        """
        try:
            query = """
            CREATE TABLE IF NOT EXISTS user_actions (
                ID INTEGER PRIMARY KEY AUTOINCREMENT,
                UserID INTEGER,
                Action TEXT NOT NULL,
                Details TEXT,
                Timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (UserID) REFERENCES users(ID)
            )
            """
            self.db_manager.execute_query(query)

            query = """
            INSERT INTO user_actions (UserID, Action, Details)
            VALUES (?, ?, ?)
            """
            self.db_manager.execute_query(query, (user_id, action, details))

        except Exception as e:
            self.logger.error(f"Ошибка логирования действия: {e}")

    def export_users_data(self, format: str = 'json') -> Optional[str]:
        """
        Экспорт данных пользователей

        Args:
            format: Формат экспорта ('json' или 'csv')

        Returns:
            Строка с данными или None в случае ошибки
        """
        users = self.get_all_users()

        if not users:
            return None

        try:
            if format == 'json':
                import json
                # Удаляем чувствительные данные
                safe_users = []
                for user in users:
                    safe_user = {
                        'ID': user['ID'],
                        'Username': user['Username'],
                        'Role': user['Role'],
                        'Password_Expiry': user['Password_Expiry'],
                        'Last_Login': user['Last_Login'],
                        'CreatedAt': user['CreatedAt'],
                        'Is_Locked': user['Is_Locked'],
                        'Password_Expired': user['Password_Expired'],
                        'Days_Until_Expiry': user['Days_Until_Expiry']
                    }
                    safe_users.append(safe_user)
                return json.dumps(safe_users, indent=2, ensure_ascii=False)

            elif format == 'csv':
                import csv
                import io

                output = io.StringIO()
                if users:
                    fieldnames = ['ID', 'Username', 'Role', 'Password_Expiry',
                                  'Last_Login', 'CreatedAt', 'Is_Locked']
                    writer = csv.DictWriter(output, fieldnames=fieldnames)
                    writer.writeheader()

                    for user in users:
                        row = {k: v for k, v in user.items() if k in fieldnames}
                        writer.writerow(row)

                return output.getvalue()

        except Exception as e:
            self.logger.error(f"Ошибка экспорта данных: {e}")
            return None


# ============= ТЕСТОВАЯ ФУНКЦИЯ ДЛЯ РАБОТЫ ЧЕРЕЗ КОНСОЛЬ =============

# def test_user_manager_console():
#     """
#     Тестовая функция для работы с БД пользователей через консоль
#     """
#     import sys
#     import os
#
#     # Добавляем путь для импорта auth
#     sys.path.append(os.path.dirname(os.path.abspath(__file__)))
#
#     from auth import DatabaseManager, Authenticator
#
#     # Настройка логирования
#     logging.basicConfig(
#         level=logging.INFO,
#         format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
#     )
#
#     print("=" * 60)
#     print("ТЕСТОВАЯ КОНСОЛЬ УПРАВЛЕНИЯ ПОЛЬЗОВАТЕЛЯМИ")
#     print("=" * 60)
#
#     # Инициализация БД
#     db_mgr = DatabaseManager("neuro_pharm_test.db")
#     if not db_mgr.connect():
#         print("❌ Ошибка подключения к БД")
#         return
#
#     # Инициализация аутентификатора для создания таблиц
#     auth = Authenticator(db_mgr)
#     if not auth.initialize_database():
#         print("❌ Ошибка инициализации БД")
#         return
#
#     # Создаем менеджер пользователей
#     user_mgr = UserManager(db_mgr)
#
#     print("✅ База данных инициализирована")
#     print("\nДоступные команды:")
#     print("  list [role] [expired] [locked] - Список пользователей")
#     print("  create <login> <password> [role] - Создать пользователя")
#     print("  info <user_id> - Информация о пользователе")
#     print("  update <user_id> [--username <name>] [--role <role>] - Обновить")
#     print("  delete <user_id> - Удалить пользователя")
#     print("  reset <user_id> <new_password> - Сбросить пароль")
#     print("  expiry <user_id> [days] - Обновить срок действия пароля")
#     print("  unlock <user_id> - Разблокировать пользователя")
#     print("  stats - Статистика")
#     print("  export [json|csv] - Экспорт данных")
#     print("  exit - Выход")
#     print("-" * 60)
#
#     # Получаем ID администратора для операций
#     admin = user_mgr.get_user_by_username("admin")
#     admin_id = admin['ID'] if admin else None
#
#     if not admin_id:
#         print("⚠️ Администратор не найден. Некоторые операции могут не работать.")
#
#     while True:
#         try:
#             command = input("\n> ").strip()
#
#             if not command:
#                 continue
#
#             parts = command.split()
#             cmd = parts[0].lower()
#
#             # LIST - Список пользователей
#             if cmd == "list":
#                 filters = {}
#
#                 # Обработка фильтров
#                 for part in parts[1:]:
#                     if part in ['user', 'senior', 'dev']:
#                         filters['role'] = part
#                     elif part == 'expired':
#                         filters['expired_passwords'] = True
#                     elif part == 'locked':
#                         filters['locked'] = True
#
#                 users = user_mgr.get_all_users(filters)
#
#                 print(f"\n📋 Список пользователей (всего: {len(users)}):")
#                 print("-" * 80)
#                 print(f"{'ID':<5} {'Логин':<20} {'Роль':<10} {'Срок пароля':<12} {'Статус':<15}")
#                 print("-" * 80)
#
#                 for user in users:
#                     status = []
#                     if user['Is_Locked']:
#                         status.append("🔒 ЗАБЛОКИРОВАН")
#                     elif user['Password_Expired']:
#                         status.append("⚠️ ПАРОЛЬ ИСТЕК")
#                     elif user['Days_Until_Expiry'] <= 14:
#                         status.append(f"⏰ {user['Days_Until_Expiry']} дн.")
#                     else:
#                         status.append("✅ Активен")
#
#                     print(f"{user['ID']:<5} {user['Username']:<20} {user['Role']:<10} "
#                           f"{user['Password_Expiry']:<12} {' '.join(status):<15}")
#
#             # CREATE - Создать пользователя
#             elif cmd == "create":
#                 if len(parts) < 3:
#                     print("❌ Использование: create <login> <password> [role]")
#                     continue
#
#                 username = parts[1]
#                 password = parts[2]
#                 role = parts[3] if len(parts) > 3 else 'user'
#
#                 success, message, user_id = user_mgr.create_user(username, password, role, admin_id)
#
#                 if success:
#                     print(f"✅ {message} (ID: {user_id})")
#                 else:
#                     print(f"❌ {message}")
#
#             # INFO - Информация о пользователе
#             elif cmd == "info":
#                 if len(parts) < 2:
#                     print("❌ Использование: info <user_id>")
#                     continue
#
#                 try:
#                     user_id = int(parts[1])
#                     user = user_mgr.get_user_info(user_id)
#
#                     if user:
#                         print(f"\n📊 Информация о пользователе ID {user_id}:")
#                         print("-" * 40)
#                         print(f"Логин: {user['Username']}")
#                         print(f"Роль: {user['Role']}")
#                         print(f"Создан: {user['CreatedAt']}")
#                         print(f"Последний вход: {user['Last_Login'] or 'Никогда'}")
#                         print(f"Срок пароля до: {user['Password_Expiry']}")
#                         print(f"Статус пароля: {'Истек' if user['Password_Expired'] else f'Действует ({user['Days_Until_Expiry']} дн.)'}")
#                         print(f"Неудачных попыток: {user.get('Failed_Attempts', 0)}")
#                         print(f"Заблокирован: {'Да' if user['Is_Locked'] else 'Нет'}")
#                         print(f"Успешных входов: {user.get('successful_logins', 0)}")
#                         print(f"Неудачных входов: {user.get('failed_logins', 0)}")
#                     else:
#                         print(f"❌ Пользователь с ID {user_id} не найден")
#
#                 except ValueError:
#                     print("❌ ID должен быть числом")
#
#             # UPDATE - Обновить пользователя
#             elif cmd == "update":
#                 if len(parts) < 3:
#                     print("❌ Использование: update <user_id> [--username <name>] [--role <role>]")
#                     continue
#
#                 try:
#                     user_id = int(parts[1])
#                     kwargs = {}
#
#                     i = 2
#                     while i < len(parts):
#                         if parts[i] == "--username" and i + 1 < len(parts):
#                             kwargs['username'] = parts[i + 1]
#                             i += 2
#                         elif parts[i] == "--role" and i + 1 < len(parts):
#                             kwargs['role'] = parts[i + 1]
#                             i += 2
#                         else:
#                             i += 1
#
#                     if not kwargs:
#                         print("❌ Не указаны параметры для обновления")
#                         continue
#
#                     success, message = user_mgr.update_user(user_id, admin_id, **kwargs)
#
#                     if success:
#                         print(f"✅ {message}")
#                     else:
#                         print(f"❌ {message}")
#
#                 except ValueError:
#                     print("❌ ID должен быть числом")
#
#             # DELETE - Удалить пользователя
#             elif cmd == "delete":
#                 if len(parts) < 2:
#                     print("❌ Использование: delete <user_id>")
#                     continue
#
#                 try:
#                     user_id = int(parts[1])
#
#                     # Подтверждение
#                     confirm = input(f"⚠️ Вы уверены, что хотите удалить пользователя ID {user_id}? (y/n): ")
#                     if confirm.lower() != 'y':
#                         print("❌ Операция отменена")
#                         continue
#
#                     success, message = user_mgr.delete_user(user_id, admin_id)
#
#                     if success:
#                         print(f"✅ {message}")
#                     else:
#                         print(f"❌ {message}")
#
#                 except ValueError:
#                     print("❌ ID должен быть числом")
#
#             # RESET - Сбросить пароль
#             elif cmd == "reset":
#                 if len(parts) < 3:
#                     print("❌ Использование: reset <user_id> <new_password>")
#                     continue
#
#                 try:
#                     user_id = int(parts[1])
#                     new_password = parts[2]
#
#                     success, message = user_mgr.reset_password(user_id, new_password, admin_id)
#
#                     if success:
#                         print(f"✅ {message}")
#                     else:
#                         print(f"❌ {message}")
#
#                 except ValueError:
#                     print("❌ ID должен быть числом")
#
#             # EXPIRY - Обновить срок действия пароля
#             elif cmd == "expiry":
#                 if len(parts) < 2:
#                     print("❌ Использование: expiry <user_id> [days]")
#                     continue
#
#                 try:
#                     user_id = int(parts[1])
#                     days = int(parts[2]) if len(parts) > 2 else None
#
#                     success, message = user_mgr.update_password_expiry(user_id, days, admin_id)
#
#                     if success:
#                         print(f"✅ {message}")
#                     else:
#                         print(f"❌ {message}")
#
#                 except ValueError:
#                     print("❌ ID и дни должны быть числами")
#
#             # UNLOCK - Разблокировать пользователя
#             elif cmd == "unlock":
#                 if len(parts) < 2:
#                     print("❌ Использование: unlock <user_id>")
#                     continue
#
#                 try:
#                     user_id = int(parts[1])
#                     success, message = user_mgr.unlock_user(user_id, admin_id)
#
#                     if success:
#                         print(f"✅ {message}")
#                     else:
#                         print(f"❌ {message}")
#
#                 except ValueError:
#                     print("❌ ID должен быть числом")
#
#             # STATS - Статистика
#             elif cmd == "stats":
#                 stats = user_mgr.get_user_statistics()
#
#                 print("\n📊 Статистика пользователей:")
#                 print("-" * 40)
#                 print(f"Всего пользователей: {stats.get('total_users', 0)}")
#                 print(f"Активных (30 дн.): {stats.get('active_users', 0)}")
#                 print(f"Истекшие пароли: {stats.get('expired_passwords', 0)}")
#                 print(f"Заблокировано: {stats.get('locked_users', 0)}")
#                 print("\nПо ролям:")
#                 for role, count in stats.get('by_role', {}).items():
#                     print(f"  {role}: {count}")
#
#             # EXPORT - Экспорт данных
#             elif cmd == "export":
#                 format_type = parts[1] if len(parts) > 1 else 'json'
#
#                 if format_type not in ['json', 'csv']:
#                     print("❌ Формат должен быть 'json' или 'csv'")
#                     continue
#
#                 data = user_mgr.export_users_data(format_type)
#
#                 if data:
#                     filename = f"users_export.{format_type}"
#                     with open(filename, 'w', encoding='utf-8') as f:
#                         f.write(data)
#                     print(f"✅ Данные экспортированы в файл: {filename}")
#                 else:
#                     print("❌ Ошибка экспорта данных")
#
#             # EXIT - Выход
#             elif cmd == "exit":
#                 print("👋 До свидания!")
#                 break
#
#             else:
#                 print(f"❌ Неизвестная команда: {cmd}")
#                 print("Введите 'help' для списка команд (в разработке)")
#
#         except KeyboardInterrupt:
#             print("\n👋 До свидания!")
#             break
#         except Exception as e:
#             print(f"❌ Ошибка: {e}")
#
#     # Закрываем соединение
#     db_mgr.disconnect()
#
# if __name__ == "__main__":
#     test_user_manager_console()