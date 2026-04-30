"""
Модуль ядра агента и менеджера базы данных (agent_core.py)

Реализует:
- DataBaseManager: Загрузка DBF-файлов и преобразование в SQLite.
- AgentCore: "Мозг" системы, который по намерению (intent) вызывает
  соответствующий обработчик для поиска в БД.
- Базовые обработчики запросов (хендлеры), реализующие конкретные сценарии поиска.
"""

import sqlite3
import json
import os
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from datetime import datetime
import logging

# Предполагаем, что библиотека dbfread установлена: pip install dbfread
from dbfread import DBF


# --- 1. Менеджер Базы Данных (Библиотекарь) ---
class DataBaseManager:
    """
    Отвечает за:
    - Подключение к SQLite.
    - Парсинг DBF-файлов из папки egk_extend306.
    - Создание и наполнение временной/рабочей SQLite БД.
    - Предоставление низкоуровневых методов поиска данных по ключам.
    """

    def __init__(self, db_path: str = "neuro_pharm_medicines.db"):
        self.db_path = db_path
        self.connection: Optional[sqlite3.Connection] = None
        self.cursor: Optional[sqlite3.Cursor] = None
        self.logger = logging.getLogger(__name__)
        self._connect()

    def _connect(self):
        """Устанавливает соединение с SQLite и включает внешние ключи."""
        try:
            self.connection = sqlite3.connect(self.db_path)
            self.connection.row_factory = sqlite3.Row
            self.cursor = self.connection.cursor()
            self.cursor.execute("PRAGMA foreign_keys = ON;")
            self.logger.info(f"Подключение к БД лекарств '{self.db_path}' установлено.")
        except sqlite3.Error as e:
            self.logger.error(f"Ошибка подключения к БД лекарств: {e}")
            raise

    def close(self):
        """Закрывает соединение с БД."""
        if self.connection:
            self.connection.close()
            self.logger.info("Соединение с БД лекарств закрыто.")

    # Исправленные методы в классе DataBaseManager

    def _create_tables_from_dbfs(self, dbf_folder: str):
        """
        Парсит структуру DBF-файлов и создает таблицы SQLite.
        """
        self.logger.info(f"Начинаем создание структуры БД из DBF в папке: {dbf_folder}")

        # Таблица INTER — перечень МНН
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS INTER (
                INTER_ID INTEGER PRIMARY KEY,
                PHAGRP_ID INTEGER,
                INTER_INN INTEGER,
                INTER_RFN TEXT,
                INVALID INTEGER DEFAULT 0
            )
        """)

        # Таблица TRADE — торговые наименования
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS TRADE (
                TRADE_ID INTEGER PRIMARY KEY,
                INTER_ID INTEGER,
                TRADE_RFN TEXT,
                INVALID INTEGER DEFAULT 0
            )
        """)

        # Таблица SICK — заболевания
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS SICK (
                SICK_ID INTEGER PRIMARY KEY,
                SICK_RFN TEXT
            )
        """)

        # Таблица SICK_TRADE — связь заболеваний с торговыми наименованиями
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS SICK_TRADE (
                SICKTRADE_ID INTEGER PRIMARY KEY,
                SICK_ID INTEGER,
                TRADE_ID INTEGER,
                FOREIGN KEY (SICK_ID) REFERENCES SICK(SICK_ID),
                FOREIGN KEY (TRADE_ID) REFERENCES TRADE(TRADE_ID)
            )
        """)

        self.connection.commit()
        self.logger.info("Структура таблиц создана.")

    def _import_dbf_data(self, dbf_folder: str):
        """
        Импортирует данные из DBF-файлов в таблицы SQLite.
        Гибко подходит к именам полей, проверяя их наличие.
        """
        self.logger.info("Начинаем импорт данных из DBF...")

        dbf_files = {
            'SICK': 'SICK.dbf',
            'TRADE': 'TRADE.dbf',
            'INTER': 'INTER.dbf',
            'SICK_TRADE': 'SICK_TRADE.dbf'
        }

        for table_name, file_name in dbf_files.items():
            file_path = os.path.join(dbf_folder, file_name)
            if not os.path.exists(file_path):
                self.logger.warning(f"Файл не найден: {file_path}")
                continue

            self.logger.info(f"Импорт {file_name} в таблицу {table_name}...")
            count = 0

            try:
                for record in DBF(file_path, encoding='windows-1251'):
                    # Нормализуем ключи: приводим к нижнему регистру
                    normalized_record = {k.lower().strip(): v for k, v in record.items()}

                    # Получаем структуру таблицы из SQLite
                    self.cursor.execute(f"PRAGMA table_info({table_name})")
                    table_columns = [col[1].lower() for col in self.cursor.fetchall()]

                    # Оставляем только те поля, которые есть в таблице
                    filtered_record = {k: v for k, v in normalized_record.items()
                                       if k in table_columns}

                    if not filtered_record:
                        self.logger.warning(f"Нет совпадающих полей для записи в {table_name}")
                        continue

                    # Строим INSERT только с совпадающими полями
                    columns = ', '.join(filtered_record.keys())
                    placeholders = ', '.join(['?' for _ in filtered_record])
                    sql = f"INSERT OR IGNORE INTO {table_name} ({columns}) VALUES ({placeholders})"

                    self.cursor.execute(sql, list(filtered_record.values()))
                    count += 1

                self.connection.commit()
                self.logger.info(f"Импортировано {count} записей в {table_name}.")

            except Exception as e:
                self.logger.error(f"Ошибка импорта {file_name}: {e}")
                # Выводим структуру DBF для отладки
                try:
                    sample = next(iter(DBF(file_path, encoding='windows-1251')))
                    self.logger.error(f"Поля DBF: {list(sample.keys())}")
                    self.cursor.execute(f"PRAGMA table_info({table_name})")
                    self.logger.error(f"Поля SQLite: {[col[1] for col in self.cursor.fetchall()]}")
                except:
                    pass

    def initialize_database(self, dbf_folder: str):
        """Полный цикл: создание таблиц и импорт данных."""
        if not os.path.exists(dbf_folder):
            self.logger.error(f"Папка с DBF не найдена: {dbf_folder}")
            raise FileNotFoundError(f"Папка с DBF не найдена: {dbf_folder}")

        self._create_tables_from_dbfs(dbf_folder)
        self._import_dbf_data(dbf_folder)

    # --- Низкоуровневые методы поиска (то, что "дергает" Агент) ---
    def find_drugs_by_disease(self, disease_name: str) -> List[Dict[str, Any]]:
        """
        Ищет торговые наименования по названию болезни.
        Пример: "грипп" -> ["Терафлю", "Колдрекс", ...]
        """
        self.logger.info(f"Поиск лекарств для болезни: '{disease_name}'")
        query = """
        SELECT DISTINCT t.TRADE_RFN
        FROM SICK s
        JOIN SICK_TRADE st ON s.SICK_ID = st.SICK_ID
        JOIN TRADE t ON st.TRADE_ID = t.TRADE_ID
        WHERE s.SICK_RFN LIKE ? AND t.INVALID = 0
        LIMIT 50
        """
        self.cursor.execute(query, (f'%{disease_name}%',))
        results = self.cursor.fetchall()
        return [dict(row) for row in results]


# --- 2. Абстрактный обработчик запросов ---
class BaseQueryHandler(ABC):
    """Базовый класс для всех обработчиков сценариев."""

    @abstractmethod
    def can_handle(self, intent: str) -> bool:
        """Проверяет, может ли этот обработчик обработать запрос."""
        pass

    @abstractmethod
    def handle(self, entities: Dict[str, Any], db_manager: DataBaseManager) -> Dict[str, Any]:
        """Выполняет обработку запроса и возвращает структурированный JSON."""
        pass


# --- 3. Конкретный обработчик: Болезнь -> Лекарство ---
class DiseaseToDrugHandler(BaseQueryHandler):
    """Реализует сценарий: поиск лекарств по названию болезни."""

    def can_handle(self, intent: str) -> bool:
        return intent == "find_drug_by_disease"

    def handle(self, entities: Dict[str, Any], db_manager: DataBaseManager) -> Dict[str, Any]:
        disease = entities.get("disease")
        if not disease:
            return {"error": "Не указано название болезни (entity: disease)"}

        drugs = db_manager.find_drugs_by_disease(disease)

        return {
            "intent": "find_drug_by_disease",
            "query": disease,
            "count": len(drugs),
            "result": [d['TRADE_RFN'] for d in drugs]  # Извлекаем только названия
        }


# --- 4. Ядро Агента (Мозг) ---
class AgentCore:
    """
    Центральный управляющий класс.
    Получает запрос от NLU-модуля, находит подходящий обработчик и запускает его.
    """

    def __init__(self, db_manager: DataBaseManager):
        self.db = db_manager
        # Реестр всех доступных сценариев обработки
        self.handlers: List[BaseQueryHandler] = [
            DiseaseToDrugHandler(),
            # В будущем здесь появятся:
            # FindAnalogHandler(),
            # CheckInteractionHandler(),
            # ...
        ]
        self.logger = logging.getLogger(__name__)

    def process_query(self, intent: str, entities: Dict[str, Any]) -> Dict[str, Any]:
        """
        Основной метод для обработки запроса.
        Args:
            intent (str): Намерение, определенное NLU (напр., "find_drug_by_disease").
            entities (Dict): Сущности, извлеченные NLU (напр., {"disease": "грипп"}).
        Returns:
            Dict: Структурированный JSON-ответ для последующей передачи в LLM.
        """
        self.logger.info(f"AgentCore: Получен запрос intent='{intent}', entities={entities}")
        for handler in self.handlers:
            if handler.can_handle(intent):
                self.logger.info(f"AgentCore: Запрос обрабатывается {handler.__class__.__name__}")
                return handler.handle(entities, self.db)

        self.logger.warning(f"AgentCore: Не найден обработчик для intent='{intent}'")
        return {"error": f"Не могу обработать запрос типа '{intent}'"}


# ============= БЛОК ТЕСТИРОВАНИЯ =============
if __name__ == "__main__":
    # Настройка логгера для тестов
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    logger = logging.getLogger(__name__)

    print("=" * 60)
    print("ТЕСТИРОВАНИЕ ЯДРА АГЕНТА И МЕНЕДЖЕРА БД")
    print("=" * 60)

    # 1. Инициализация
    DBF_FOLDER = "egk_extend306"
    db_manager = DataBaseManager()

    try:
        # 2. Загрузка данных (только при первом запуске или если БД нет)
        # В реальном приложении здесь будет проверка даты обновления и т.д.
        logger.info("Пытаемся инициализировать БД лекарств из DBF...")
        db_manager.initialize_database(DBF_FOLDER)
        logger.info("База данных готова к работе.")

        # 3. Создаем ядро агента
        agent = AgentCore(db_manager)

        # 4. Симуляция запроса от NLU
        # Представим, что NLU уже отработал и прислал нам:
        test_intent = "find_drug_by_disease"
        test_entities = {"disease": "грипп"}

        print(f"\n--- Симуляция запроса ---")
        print(f"Intent: {test_intent}")
        print(f"Entities: {test_entities}")
        print("-" * 30)

        # 5. Запуск ядра агента
        response = agent.process_query(test_intent, test_entities)

        # 6. Вывод результата
        print("Результат обработки запроса (JSON):")
        print(json.dumps(response, ensure_ascii=False, indent=2))

    except FileNotFoundError as e:
        logger.error(f"Критическая ошибка: {e}")
        logger.info("Создайте папку 'egk_extend306' и поместите туда DBF-файлы для продолжения.")
    except Exception as e:
        logger.exception("Произошла непредвиденная ошибка.")
    finally:
        # 7. Закрываем соединение с БД
        if db_manager:
            db_manager.close()