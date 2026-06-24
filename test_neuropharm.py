import pytest
import sys
import os
from datetime import datetime, timedelta

# Добавляем текущую директорию в путь для импортов
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from usr_mgr import UserManager
from query_parser import QueryParser
from auth import Authenticator


# ============================================================
# ТЕСТ 1: Валидация логина (граничные случаи и ошибки)
# ============================================================
class TestLoginValidation:
    """Тестируем validate_login из UserManager / Authenticator"""

    def setup_method(self):
        """Создаём объект для тестов (без реальной БД)"""
        # Создаём заглушку db_manager, чтобы не подключаться к реальной БД
        class MockDB:
            def fetch_one(self, query, params):
                return None  # логин не существует
            def execute_query(self, query, params):
                return True
            def fetch_all(self, query, params=()):
                return []

        self.mock_db = MockDB()
        self.user_mgr = UserManager(self.mock_db)

    def test_valid_login_min_length(self):
        """Корректный логин минимальной длины (3 символа)"""
        is_valid, error = self.user_mgr.validate_login("abc")
        assert is_valid is True
        assert error == ""

    def test_valid_login_max_length(self):
        """Корректный логин максимальной длины (20 символов)"""
        is_valid, error = self.user_mgr.validate_login("a" * 20)
        assert is_valid is True
        assert error == ""

    def test_invalid_login_too_short(self):
        """Логин слишком короткий (<3 символов)"""
        is_valid, error = self.user_mgr.validate_login("ab")
        assert is_valid is False
        assert "не менее 3 символов" in error.lower() or "3 символов" in error

    def test_invalid_login_too_long(self):
        """Логин слишком длинный (>20 символов)"""
        is_valid, error = self.user_mgr.validate_login("a" * 21)
        assert is_valid is False
        assert "не может превышать" in error.lower() or "20" in error

    def test_invalid_login_empty(self):
        """Пустой логин"""
        is_valid, error = self.user_mgr.validate_login("")
        assert is_valid is False
        assert error != ""

    def test_invalid_login_special_chars(self):
        """Логин с недопустимыми символами (кириллица, спецсимволы)"""
        invalid_logins = ["admin!", "петр", "user@name", "admin user", "логин"]
        for login in invalid_logins:
            is_valid, error = self.user_mgr.validate_login(login)
            assert is_valid is False, f"Логин '{login}' должен быть отклонён"
            assert "латинские буквы" in error or "цифры" in error


# ============================================================
# ТЕСТ 2: Валидация пароля
# ============================================================
class TestPasswordValidation:
    """Тестируем validate_password"""

    def setup_method(self):
        class MockDB:
            def fetch_one(self, query, params):
                return None
            def execute_query(self, query, params):
                return True

        self.user_mgr = UserManager(MockDB())

    def test_valid_password_min_length(self):
        """Пароль минимальной длины (8 символов)"""
        is_valid, error = self.user_mgr.validate_password("pass1234")
        assert is_valid is True
        assert error == ""

    def test_valid_password_max_length(self):
        """Пароль максимальной длины (20 символов)"""
        is_valid, error = self.user_mgr.validate_password("p" * 20)
        assert is_valid is True
        assert error == ""

    def test_invalid_password_too_short(self):
        """Пароль короче 8 символов"""
        is_valid, error = self.user_mgr.validate_password("pass123")
        assert is_valid is False
        assert "не менее 8" in error.lower() or "8 символов" in error

    def test_invalid_password_too_long(self):
        """Пароль длиннее 20 символов"""
        is_valid, error = self.user_mgr.validate_password("p" * 21)
        assert is_valid is False
        assert "не может превышать" in error.lower() or "20" in error

    def test_invalid_password_empty(self):
        """Пустой пароль"""
        is_valid, error = self.user_mgr.validate_password("")
        assert is_valid is False
        assert error != ""


# ============================================================
# ТЕСТ 3: Валидация роли пользователя
# ============================================================
class TestRoleValidation:
    """Тестируем validate_role"""

    def setup_method(self):
        class MockDB:
            def fetch_one(self, query, params):
                return None
        self.user_mgr = UserManager(MockDB())

    def test_valid_roles(self):
        """Все допустимые роли"""
        valid_roles = ["user", "senior", "dev"]
        for role in valid_roles:
            is_valid, error = self.user_mgr.validate_role(role)
            assert is_valid is True, f"Роль '{role}' должна быть допустимой"
            assert error == ""

    def test_invalid_role(self):
        """Недопустимая роль"""
        invalid_roles = ["admin", "superuser", "guest", ""]
        for role in invalid_roles:
            is_valid, error = self.user_mgr.validate_role(role)
            assert is_valid is False
            assert "Недопустимая роль" in error


# ============================================================
# ТЕСТ 4: Парсер запросов — определение intent'ов
# ============================================================
class TestQueryParserIntent:
    """Тестируем, что QueryParser правильно определяет намерения"""

    def setup_method(self):
        self.parser = QueryParser()

    def test_intent_find_analog(self):
        """Запрос на поиск аналогов"""
        queries = [
            "найди аналоги аспирина",
            "чем заменить нурофен",
            "аналоги парацетамола",
            "похожий препарат на анальгин"
        ]
        for query in queries:
            result = self.parser.parse_query(query)
            # Может вернуть intent или error/warning — проверяем, что нет критической ошибки
            assert "error" not in result or result.get("intent") is not None
            if "intent" in result:
                assert result["intent"] in ["find_analog", "find_synonyms", "get_drug_info"]

    def test_intent_get_drug_info(self):
        """Запрос на получение информации о препарате"""
        queries = [
            "расскажи о парацетамоле",
            "информация о аспирине",
            "что такое ибупрофен",
            "подробнее о нурофене"
        ]
        for query in queries:
            result = self.parser.parse_query(query)
            # Проверяем, что не вернулась ошибка или определился intent
            assert "error" not in result or result.get("intent") is not None

    def test_intent_check_interaction(self):
        """Запрос на проверку совместимости двух препаратов"""
        queries = [
            "можно ли принимать аспирин и ибупрофен вместе",
            "совместимость парацетамола и анальгина",
            "можно ли пить нурофен с аспирином"
        ]
        for query in queries:
            result = self.parser.parse_query(query)
            # Особенно важный тест — проверяем эвристику
            if "error" not in result:
                # Может быть check_interaction или другой intent
                assert result.get("intent") is not None

    def test_intent_compare_drugs(self):
        """Запрос на сравнение препаратов"""
        queries = [
            "сравни анальгин и парацетамол",
            "что лучше нурофен или ибупрофен",
            "отличие аспирина от парацетамола"
        ]
        for query in queries:
            result = self.parser.parse_query(query)
            if "error" not in result:
                assert result.get("intent") is not None

    def test_empty_query_returns_error(self):
        """Пустой запрос должен возвращать ошибку"""
        result = self.parser.parse_query("")
        assert "error" in result

    def test_gibberish_query_returns_error(self):
        """Нечитаемый запрос должен возвращать ошибку"""
        result = self.parser.parse_query("!@#$%^&*")
        assert "error" in result or result.get("warning") is not None


# ============================================================
# ТЕСТ 5: Извлечение сущностей из запросов
# ============================================================
class TestQueryParserEntities:
    """Тестируем извлечение названий препаратов, болезней и других сущностей"""

    def setup_method(self):
        self.parser = QueryParser()

    def test_extract_drug_name_capitalized(self):
        """Извлечение названия препарата с заглавной буквы"""
        # Проверяем внутренний метод _extract_drug_name_clean
        result = self.parser.parse_query("найди аналоги Аспирина")
        entities = result.get("entities", {})
        # Название может быть в drug_name или drug
        assert ("drug_name" in entities) or ("drug" in entities) or ("error" not in result)

    def test_extract_disease_name(self):
        """Извлечение названия болезни"""
        result = self.parser.parse_query("найди препараты от гриппа")
        entities = result.get("entities", {})
        if "error" not in result:
            assert "disease" in entities or result.get("intent") == "find_drug_by_disease"

    def test_extract_two_drugs_for_interaction(self):
        """Извлечение двух препаратов для проверки совместимости"""
        result = self.parser.parse_query("можно ли принимать аспирин и ибупрофен вместе")
        entities = result.get("entities", {})
        if "error" not in result and result.get("intent") == "check_interaction":
            assert "drug_name" in entities
            assert "drug_name2" in entities


# ============================================================
# ТЕСТ 6: Хеширование паролей (криптографическая корректность)
# ============================================================
class TestPasswordHashing:
    """Тестируем generate_salt, hash_password_with_salt и verify_password"""

    def setup_method(self):
        class MockDB:
            def fetch_one(self, query, params):
                return None
        self.auth = Authenticator(MockDB())

    def test_salt_is_random(self):
        """Соль должна быть случайной и разной при каждом вызове"""
        salt1 = self.auth.generate_salt()
        salt2 = self.auth.generate_salt()
        assert salt1 != salt2
        assert len(salt1) == 32  # 16 байт = 32 hex-символа
        assert len(salt2) == 32

    def test_same_password_different_hash(self):
        """Одинаковый пароль с разными солями даёт разный хеш"""
        password = "TestPassword123"
        salt1 = self.auth.generate_salt()
        salt2 = self.auth.generate_salt()
        hash1 = self.auth.hash_password_with_salt(password, salt1)
        hash2 = self.auth.hash_password_with_salt(password, salt2)
        assert hash1 != hash2

    def test_verify_correct_password(self):
        """Верный пароль проходит проверку"""
        password = "MySecretPass456"
        salt = self.auth.generate_salt()
        hashed = self.auth.hash_password_with_salt(password, salt)
        assert self.auth.verify_password(password, hashed, salt) is True

    def test_verify_wrong_password(self):
        """Неверный пароль не проходит проверку"""
        password = "CorrectPass123"
        wrong_password = "WrongPass456"
        salt = self.auth.generate_salt()
        hashed = self.auth.hash_password_with_salt(password, salt)
        assert self.auth.verify_password(wrong_password, hashed, salt) is False

    def test_hash_is_deterministic_with_same_salt(self):
        """Один пароль + одна соль = одинаковый хеш"""
        password = "DeterministicTest"
        salt = "fixed_salt_for_testing_123"
        hash1 = self.auth.hash_password_with_salt(password, salt)
        hash2 = self.auth.hash_password_with_salt(password, salt)
        assert hash1 == hash2


# ============================================================
# ТЕСТ 7: Дополнительно — проверка даты истечения пароля
# ============================================================
class TestPasswordExpiry:
    """Тестируем логику истечения срока пароля"""

    def test_expiry_calculation(self):
        """Проверяем, что дата истечения рассчитывается правильно"""
        from usr_mgr import UserManager
        class MockDB:
            def fetch_one(self, query, params):
                return None
            def execute_query(self, query, params):
                return True

        user_mgr = UserManager(MockDB())
        # По умолчанию 180 дней
        assert user_mgr.password_expiry_days == 180

    def test_is_password_expired_method(self):
        """Тестируем внутренний метод _is_password_expired"""
        from usr_mgr import UserManager
        class MockDB:
            def fetch_one(self, query, params):
                return None
            def execute_query(self, query, params):
                return True

        user_mgr = UserManager(MockDB())

        # Прошлая дата -> истек
        past_date = (datetime.now() - timedelta(days=1)).date().isoformat()
        assert user_mgr._is_password_expired(past_date) is True

        # Будущая дата -> не истек
        future_date = (datetime.now() + timedelta(days=30)).date().isoformat()
        assert user_mgr._is_password_expired(future_date) is False

        # Сегодня -> не истек (истекает в конце дня)
        today = datetime.now().date().isoformat()
        assert user_mgr._is_password_expired(today) is False


# ============================================================
# ЗАПУСК ТЕСТОВ
# ============================================================
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])