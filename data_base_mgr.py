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
from query_parser import QueryParser

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

    def initialize_database(self, dbf_folder: str):
        """Создаёт все таблицы и наполняет их данными из DBF."""
        if not os.path.exists(dbf_folder):
            raise FileNotFoundError(f"Папка {dbf_folder} не найдена")

        dbf_files = [
            'SICK.dbf', 'TRADE.dbf', 'INTER.dbf', 'SICK_TRADE.dbf',
            'FIRM.dbf', 'COUNTRY.dbf', 'DRUGFORM.dbf', 'GENFORM.dbf',
            'PRODFORM.dbf', 'MEDICINE.dbf', 'DRUGS.dbf',
            'MASSUNIT.dbf', 'CUBEUNIT.dbf', 'CONCUNIT.dbf', 'UNITUNIT.dbf',
            'CHE_OUT.dbf', 'PHARMGRP.dbf'
        ]

        for file_name in dbf_files:
            file_path = os.path.join(dbf_folder, file_name)
            if not os.path.exists(file_path):
                self.logger.warning(f"Файл {file_name} пропущен (не найден)")
                continue
            table_name = os.path.splitext(file_name)[0]
            try:
                self._create_table_from_dbf(table_name, file_path)
                self._import_dbf_to_table(table_name, file_path)
            except Exception as e:
                self.logger.error(f"КРИТИЧЕСКАЯ ОШИБКА при обработке {file_name}: {e}", exc_info=True)

    def _create_table_from_dbf(self, table_name: str, dbf_path: str):
        """Создаёт таблицу SQLite с колонками, в точности как в DBF."""
        try:
            dbf = DBF(dbf_path, encoding='windows-1251')
            sample = next(iter(dbf))

            # Собираем ВСЕ имена полей из первой записи
            field_names = []
            for field_name in sample.keys():
                clean = field_name.strip()
                if not clean:
                    self.logger.warning(f"Пустое имя поля в {table_name}, пропускаем")
                    continue
                field_names.append(clean)

            # Определяем, есть ли поле, которое можно сделать PRIMARY KEY
            # Приоритет: поле, совпадающее с именем таблицы + _ID (например, DRUGS_ID для таблицы DRUGS)
            # Если такого нет — берём первое поле, заканчивающееся на _ID
            # Если и таких нет — PRIMARY KEY не будет (добавим rowid)
            pk_field = None
            expected_pk = f"{table_name}_ID"

            for fname in field_names:
                if fname.upper() == expected_pk.upper():
                    pk_field = fname
                    break

            if not pk_field:
                for fname in field_names:
                    if fname.upper().endswith('_ID'):
                        pk_field = fname
                        break

            # Строим определение колонок
            columns_def = []
            for fname in field_names:
                if pk_field and fname.upper() == pk_field.upper():
                    columns_def.append(f'"{fname}" INTEGER PRIMARY KEY')
                else:
                    columns_def.append(f'"{fname}" TEXT')

            if not pk_field:
                self.logger.warning(f"Таблица {table_name}: PRIMARY KEY не найден, будет использован rowid")

            sql = f"CREATE TABLE IF NOT EXISTS {table_name} ({', '.join(columns_def)})"
            self.cursor.execute(sql)
            self.connection.commit()
            self.logger.info(f"Таблица {table_name} создана ({len(columns_def)} колонок, PK: {pk_field or 'нет'})")

        except Exception as e:
            self.logger.error(f"Ошибка создания таблицы {table_name} из {dbf_path}: {e}")
            raise

    def _import_dbf_to_table(self, table_name: str, dbf_path: str):
        """Импортирует все записи из DBF в соответствующую таблицу SQLite."""
        self.logger.info(f"Импорт {os.path.basename(dbf_path)} -> {table_name}...")
        count = 0
        skipped_fields = set()
        try:
            # Получаем список колонок, которые РЕАЛЬНО есть в SQLite таблице
            self.cursor.execute(f"PRAGMA table_info({table_name})")
            existing_columns = {col[1].upper() for col in self.cursor.fetchall()}

            dbf = DBF(dbf_path, encoding='windows-1251')

            for record in dbf:
                # Нормализуем имена полей из DBF
                normalized = {}
                for k, v in record.items():
                    clean = k.strip()
                    if not clean:
                        continue
                    # Проверяем, есть ли такая колонка в SQLite (без учёта регистра)
                    if clean.upper() in existing_columns:
                        normalized[clean] = v
                    else:
                        skipped_fields.add(clean)

                if not normalized:
                    continue

                cols = ', '.join(f'"{k}"' for k in normalized.keys())
                placeholders = ', '.join(['?'] * len(normalized))
                sql = f"INSERT OR IGNORE INTO {table_name} ({cols}) VALUES ({placeholders})"
                self.cursor.execute(sql, list(normalized.values()))
                count += 1

            self.connection.commit()
            if skipped_fields:
                self.logger.warning(f"Пропущены поля (отсутствуют в SQLite): {', '.join(skipped_fields)}")
            self.logger.info(f"Импортировано {count} записей в {table_name}")

        except Exception as e:
            self.logger.error(f"Ошибка импорта {dbf_path}: {e}")
            raise

    def _find_trade_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Поиск торгового наименования по неточному названию.
        Возвращает запись из TRADE или None.
        """
        # 1. Точное совпадение (LIKE)
        trade = self.cursor.execute(
            "SELECT TRADE_ID, TRADE_RFN, INTER_ID FROM TRADE WHERE TRADE_RFN LIKE ? AND INVALID = 0",
            (f'%{name}%',)
        ).fetchone()
        if trade:
            return trade

        # 2. Поиск по отдельным словам (самое длинное слово)
        words = name.split()
        if len(words) > 1:
            for word in sorted(words, key=len, reverse=True):
                if len(word) >= 3:
                    trade = self.cursor.execute(
                        "SELECT TRADE_ID, TRADE_RFN, INTER_ID FROM TRADE WHERE TRADE_RFN LIKE ? AND INVALID = 0",
                        (f'%{word}%',)
                    ).fetchone()
                    if trade:
                        self.logger.info(f"Найдено по слову '{word}': {trade['TRADE_RFN']}")
                        return trade

        # 3. Попытка отсечения возможного окончания
        # Убираем последние 1-3 буквы и пробуем найти
        for trim in range(1, 4):
            if len(name) > trim + 3:
                trimmed = name[:-trim]
                trade = self.cursor.execute(
                    "SELECT TRADE_ID, TRADE_RFN, INTER_ID FROM TRADE WHERE TRADE_RFN LIKE ? AND INVALID = 0",
                    (f'%{trimmed}%',)
                ).fetchone()
                if trade:
                    self.logger.info(f"Найдено по усечённому названию '{trimmed}': {trade['TRADE_RFN']}")
                    return trade

        return None

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

    def get_drug_full_info(self, trade_name: str) -> Dict[str, Any]:
        self.logger.info(f"Запрос полной информации о препарате: '{trade_name}'")

        trade = self._find_trade_by_name(trade_name)
        if not trade:
            return {"error": f"Препарат '{trade_name}' не найден"}

        trade_id = trade['TRADE_ID']
        inter_id = trade['INTER_ID']

        # МНН
        inter = self.cursor.execute(
            "SELECT INTER_RFN FROM INTER WHERE INTER_ID = ?",
            (inter_id,)
        ).fetchone()

        # Упаковки через DRUGS + MEDICINE + FIRM + COUNTRY
        drugs = self.cursor.execute("""
            SELECT d.DRUG_NAME, m.MED_DOSE, d.FORM_RFN, d.NOM_QTTY,
                   f.FIRM_RFN, c.CNTRY_RFN, d.CHECK_DATE
            FROM DRUGS d
            LEFT JOIN MEDICINE m ON d.MED_ID = m.MED_ID
            LEFT JOIN FIRM f ON d.FIRM_ID = f.FIRM_ID
            LEFT JOIN COUNTRY c ON d.CNTRY_ID = c.CNTRY_ID
            WHERE d.TRADE_ID = ? AND d.INVALID = 0
            ORDER BY d.CHECK_DATE DESC
            LIMIT 20
        """, (trade_id,)).fetchall()

        return {
            "trade_name": trade['TRADE_RFN'],
            "mnn": inter['INTER_RFN'] if inter else None,
            "packages": [dict(row) for row in drugs],
            "total_packages": len(drugs)
        }

    def get_synonyms_by_mnn(self, mnn_name: str) -> List[Dict[str, Any]]:
        """
        Находит все торговые наименования по международному непатентованному названию.
        Пример: "Парацетамол" -> ["Панадол", "Эффералган", "Цефекон", ...]
        """
        self.logger.info(f"Поиск синонимов для МНН: '{mnn_name}'")

        query = """
        SELECT t.TRADE_RFN, t.TRADE_ID
        FROM INTER i
        JOIN TRADE t ON i.INTER_ID = t.INTER_ID
        WHERE i.INTER_RFN LIKE ? AND t.INVALID = 0 AND i.INVALID = 0
        ORDER BY t.TRADE_RFN
        LIMIT 100
        """
        results = self.cursor.execute(query, (f'%{mnn_name}%',)).fetchall()
        return [dict(row) for row in results]

    def get_analogs_by_drug(self, trade_name: str) -> Dict[str, Any]:
        self.logger.info(f"Поиск синонимов и аналогов для: '{trade_name}'")

        trade = self._find_trade_by_name(trade_name)
        if not trade:
            return {"error": f"Препарат '{trade_name}' не найден"}

        trade_id = trade['TRADE_ID']
        inter_id = trade['INTER_ID']

        # Получаем фармгруппу через INTER
        inter = self.cursor.execute(
            "SELECT PHAGRP_ID FROM INTER WHERE INTER_ID = ?",
            (inter_id,)
        ).fetchone()

        pharmgrp_id = inter['PHAGRP_ID'] if inter else None

        # Аналоги по тому же МНН (полные аналоги)
        same_mnn = self.cursor.execute("""
            SELECT DISTINCT t.TRADE_RFN
            FROM TRADE t
            WHERE t.INTER_ID = ? AND t.INVALID = 0 AND t.TRADE_RFN NOT LIKE ?
            LIMIT 50
        """, (inter_id, f'%{trade_name}%')).fetchall()

        # Терапевтические аналоги (та же фармгруппа, другое МНН)
        same_group = []
        if pharmgrp_id:
            same_group = self.cursor.execute("""
                SELECT DISTINCT t.TRADE_RFN, i.INTER_RFN
                FROM TRADE t
                JOIN INTER i ON t.INTER_ID = i.INTER_ID
                WHERE i.PHAGRP_ID = ? AND i.INTER_ID != ? AND t.INVALID = 0
                LIMIT 30
            """, (pharmgrp_id, inter_id)).fetchall()

        return {
            "drug": trade_name,
            "synonyms": [row['TRADE_RFN'] for row in same_mnn],
            "analogs": [
                {"trade": row['TRADE_RFN'], "mnn": row['INTER_RFN']}
                for row in same_group
            ]
        }
    # ------------------ ФИЛЬТРЫ ДЛЯ ПРОДВИНУТОГО ПОЛЬЗОВАТЕЛЯ ------------------
    def search_drugs_by_manufacturer(self, firm_name: str) -> Dict[str, Any]:
        """Поиск препаратов по производителю."""
        self.logger.info(f"Поиск препаратов производителя: '{firm_name}'")
        query = """
        SELECT DISTINCT t.TRADE_RFN, d.DRUG_NAME, f.FIRM_RFN
        FROM DRUGS d
        JOIN FIRM f ON d.FIRM_ID = f.FIRM_ID
        JOIN TRADE t ON d.TRADE_ID = t.TRADE_ID
        WHERE f.FIRM_RFN LIKE ? AND d.INVALID = 0 AND t.INVALID = 0
        LIMIT 100
        """
        rows = self.cursor.execute(query, (f'%{firm_name}%',)).fetchall()
        return {
            "manufacturer": firm_name,
            "count": len(rows),
            "drugs": [dict(r) for r in rows]
        }

    def search_drugs_by_country(self, country_name: str) -> Dict[str, Any]:
        """Поиск препаратов по стране производителя."""
        self.logger.info(f"Поиск препаратов страны: '{country_name}'")
        query = """
        SELECT DISTINCT t.TRADE_RFN, d.DRUG_NAME, c.CNTRY_RFN
        FROM DRUGS d
        JOIN COUNTRY c ON d.CNTRY_ID = c.CNTRY_ID
        JOIN TRADE t ON d.TRADE_ID = t.TRADE_ID
        WHERE c.CNTRY_RFN LIKE ? AND d.INVALID = 0 AND t.INVALID = 0
        LIMIT 100
        """
        rows = self.cursor.execute(query, (f'%{country_name}%',)).fetchall()
        return {
            "country": country_name,
            "count": len(rows),
            "drugs": [dict(r) for r in rows]
        }

    def search_drugs_by_form(self, form_name: str) -> Dict[str, Any]:
        """
        Поиск по лекарственной форме (например, "таблетки", "раствор").
        Ищем в DRUGFORM и GENFORM.
        """
        self.logger.info(f"Поиск по лекарственной форме: '{form_name}'")
        query = """
        SELECT DISTINCT t.TRADE_RFN, d.DRUG_NAME, df.DRUGF_RFN, gf.GENF_RFN
        FROM DRUGS d
        JOIN DRUGFORM df ON d.DRUGF_ID = df.DRUGF_ID
        LEFT JOIN GENFORM gf ON d.GENF_ID = gf.GENF_ID
        JOIN TRADE t ON d.TRADE_ID = t.TRADE_ID
        WHERE (df.DRUGF_RFN LIKE ? OR gf.GENF_RFN LIKE ?)
          AND d.INVALID = 0 AND t.INVALID = 0
        LIMIT 100
        """
        rows = self.cursor.execute(query, (f'%{form_name}%', f'%{form_name}%')).fetchall()
        return {
            "form": form_name,
            "count": len(rows),
            "drugs": [dict(r) for r in rows]
        }

    def search_drugs_by_dosage(self, dosage_value: float, unit: Optional[str] = None) -> Dict[str, Any]:
        """
        Поиск препаратов по дозировке. При указании единицы измерения пытается
        учесть связь с соответствующей таблицей единиц.
        """
        self.logger.info(f"Поиск по дозировке: {dosage_value} {unit or ''}")
        results = []

        # 1. Поиск по текстовому полю MED_DOSE (в таблице MEDICINE)
        # Предполагаем, что dosage_value передаётся как число, но ищем текстовое вхождение
        if unit:
            pattern = f"%{dosage_value}%{unit}%"
        else:
            pattern = f"%{dosage_value}%"
        rows_dose = self.cursor.execute("""
            SELECT DISTINCT t.TRADE_RFN, m.MED_NAME, m.MED_DOSE
            FROM MEDICINE m
            JOIN DRUGS d ON d.MED_ID = m.MED_ID
            JOIN TRADE t ON d.TRADE_ID = t.TRADE_ID
            WHERE m.MED_DOSE LIKE ? AND d.INVALID = 0
            LIMIT 50
        """, (pattern,)).fetchall()
        results.extend([dict(r) for r in rows_dose])

        # 2. Поиск по числовым полям в DRUGS с учётом единиц
        # Если unit задан, пытаемся определить, к какому типу относится (масса, объём, концентрация, ед. действия)
        # Для простоты ищем во всех числовых полях с LIKE по соответствующей единице
        if unit:
            # Пытаемся найти подходящий ID единицы в справочниках
            mass_ids = []
            cube_ids = []
            conc_ids = []
            unit_ids = []
            for row in self.cursor.execute("SELECT MASS_ID FROM MASSUNIT WHERE MASS_RFN LIKE ?", (f'%{unit}%',)):
                mass_ids.append(row['MASS_ID'])
            for row in self.cursor.execute("SELECT CUBE_ID FROM CUBEUNIT WHERE CUBE_RFN LIKE ?", (f'%{unit}%',)):
                cube_ids.append(row['CUBE_ID'])
            for row in self.cursor.execute("SELECT CONC_ID FROM CONCUNIT WHERE CONC_RFN LIKE ?", (f'%{unit}%',)):
                conc_ids.append(row['CONC_ID'])
            for row in self.cursor.execute("SELECT UNIT_ID FROM UNITUNIT WHERE UNIT_RFN LIKE ?", (f'%{unit}%',)):
                unit_ids.append(row['UNIT_ID'])

            # Теперь ищем препараты, где значение и единица совпадают
            queries = []
            params = []
            if mass_ids:
                queries.append("(d.AMASS_QTTY = ? AND d.AMASS_ID IN ({}))".format(','.join(['?']*len(mass_ids))))
                params.extend([dosage_value] + mass_ids)
            if cube_ids:
                queries.append("(d.CUBE_QTTY = ? AND d.CUBE_ID IN ({}))".format(','.join(['?']*len(cube_ids))))
                params.extend([dosage_value] + cube_ids)
            if conc_ids:
                queries.append("(d.CONC_QTTY = ? AND d.CONC_ID IN ({}))".format(','.join(['?']*len(conc_ids))))
                params.extend([dosage_value] + conc_ids)
            if unit_ids:
                queries.append("(d.UNIT_QTTY = ? AND d.UNIT_ID IN ({}))".format(','.join(['?']*len(unit_ids))))
                params.extend([dosage_value] + unit_ids)

            if queries:
                combined = " OR ".join(queries)
                sql = f"""
                    SELECT DISTINCT t.TRADE_RFN, d.DRUG_NAME
                    FROM DRUGS d
                    JOIN TRADE t ON d.TRADE_ID = t.TRADE_ID
                    WHERE ({combined}) AND d.INVALID = 0
                    LIMIT 50
                """
                rows_units = self.cursor.execute(sql, params).fetchall()
                results.extend([dict(r) for r in rows_units])
        else:
            # Ищем просто по числовым полям без привязки к единице
            rows_num = self.cursor.execute("""
                SELECT DISTINCT t.TRADE_RFN, d.DRUG_NAME
                FROM DRUGS d
                JOIN TRADE t ON d.TRADE_ID = t.TRADE_ID
                WHERE (d.AMASS_QTTY = ? OR d.CUBE_QTTY = ? OR d.CONC_QTTY = ? OR d.UNIT_QTTY = ? OR d.DOSE_QTTY = ?)
                  AND d.INVALID = 0
                LIMIT 50
            """, (dosage_value,)*5).fetchall()
            results.extend([dict(r) for r in rows_num])

        # Убираем дубликаты
        unique = {r.get('TRADE_RFN') or r.get('DRUG_NAME'): r for r in results}
        return {
            "dosage": f"{dosage_value} {unit or ''}",
            "count": len(unique),
            "drugs": list(unique.values())
        }

    # ------------------ МЕТОДЫ РАСШИРЕННОГО ФУНКЦИОНАЛА (ТЗ п. 4.6) ------------------
    def compare_drugs(self, trade_name1: str, trade_name2: str) -> Dict[str, Any]:
        """
        Сравнение двух препаратов по ключевым атрибутам:
        МНН, фармгруппа, производители, формы выпуска, страны.
        """
        self.logger.info(f"Сравнение препаратов: '{trade_name1}' и '{trade_name2}'")

        def get_drug_data(name):
            trade = self._find_trade_by_name(name)
            if not trade:
                return None

            inter = self.cursor.execute(
                "SELECT INTER_RFN, PHAGRP_ID FROM INTER WHERE INTER_ID = ?",
                (trade['INTER_ID'],)
            ).fetchone()

            pharmgrp = None
            if inter:
                grp = self.cursor.execute(
                    "SELECT PHAGRP_NAM FROM PHARMGRP WHERE PHAGRP_ID = ?",
                    (inter['PHAGRP_ID'],)
                ).fetchone()
                pharmgrp = grp['PHAGRP_NAM'] if grp else None

            firms = self.cursor.execute("""
                SELECT DISTINCT f.FIRM_RFN
                FROM DRUGS d
                JOIN FIRM f ON d.FIRM_ID = f.FIRM_ID
                WHERE d.TRADE_ID = ? AND d.INVALID = 0
                LIMIT 5
            """, (trade['TRADE_ID'],)).fetchall()

            forms = self.cursor.execute("""
                SELECT DISTINCT df.DRUGF_RFN
                FROM DRUGS d
                JOIN DRUGFORM df ON d.DRUGF_ID = df.DRUGF_ID
                WHERE d.TRADE_ID = ? AND d.INVALID = 0
                LIMIT 5
            """, (trade['TRADE_ID'],)).fetchall()

            return {
                "trade_name": trade['TRADE_RFN'],
                "mnn": inter['INTER_RFN'] if inter else None,
                "pharm_group": pharmgrp,
                "manufacturers": [f['FIRM_RFN'] for f in firms],
                "forms": [f['DRUGF_RFN'] for f in forms]
            }

        drug1_data = get_drug_data(trade_name1)
        drug2_data = get_drug_data(trade_name2)

        if not drug1_data:
            return {"error": f"Препарат '{trade_name1}' не найден"}
        if not drug2_data:
            return {"error": f"Препарат '{trade_name2}' не найден"}

        # Сравнение
        same_mnn = drug1_data["mnn"] == drug2_data["mnn"]
        same_group = drug1_data["pharm_group"] == drug2_data["pharm_group"]
        common_manufacturers = set(drug1_data["manufacturers"]) & set(drug2_data["manufacturers"])
        common_forms = set(drug1_data["forms"]) & set(drug2_data["forms"])

        return {
            "drug1": drug1_data,
            "drug2": drug2_data,
            "comparison": {
                "same_mnn": same_mnn,
                "same_pharm_group": same_group,
                "common_manufacturers": list(common_manufacturers),
                "common_forms": list(common_forms)
            }
        }

    def check_drug_interaction(self, trade_name1: str, trade_name2: str) -> Dict[str, Any]:
        """
        Проверка совместного применения двух препаратов.
        Анализирует фармгруппы и МНН на предмет возможного взаимодействия.
        """
        self.logger.info(f"Проверка взаимодействия: '{trade_name1}' и '{trade_name2}'")

        def get_drug_pharm_info(name):
            trade = self._find_trade_by_name(name)
            if not trade:
                return None

            inter = self.cursor.execute(
                "SELECT INTER_RFN, PHAGRP_ID FROM INTER WHERE INTER_ID = ?",
                (trade['INTER_ID'],)
            ).fetchone()

            return {
                "trade_name": trade['TRADE_RFN'],
                "mnn": inter['INTER_RFN'] if inter else None,
                "pharmgrp_id": inter['PHAGRP_ID'] if inter else None
            }

        drug1 = get_drug_pharm_info(trade_name1)
        drug2 = get_drug_pharm_info(trade_name2)

        if not drug1:
            return {"error": f"Препарат '{trade_name1}' не найден"}
        if not drug2:
            return {"error": f"Препарат '{trade_name2}' не найден"}

        # Проверка на идентичность МНН (риск передозировки)
        same_mnn = drug1["mnn"] == drug2["mnn"]

        # Проверка на одну фармгруппу (возможна конкуренция или усиление эффекта)
        same_group = drug1["pharmgrp_id"] == drug2["pharmgrp_id"]

        # Формируем предупреждения
        warnings = []
        if same_mnn:
            warnings.append("Препараты содержат одинаковое действующее вещество — риск передозировки!")
        if same_group:
            warnings.append(
                "Препараты относятся к одной фармацевтической группе — возможно усиление эффекта или побочных действий.")

        return {
            "drug1": drug1["trade_name"],
            "drug2": drug2["trade_name"],
            "same_mnn": same_mnn,
            "same_pharm_group": same_group,
            "warnings": warnings if warnings else ["Данных о взаимодействии не найдено. Проконсультируйтесь с врачом."]
        }

    def get_drug_side_effects(self, trade_name: str) -> Dict[str, Any]:
        """
        Возвращает список побочных эффектов препарата.
        Так как в текущей структуре DBF нет отдельной таблицы побочных эффектов,
        используется поиск по связанным данным (МНН, фармгруппа).
        """
        self.logger.info(f"Запрос побочных эффектов для: '{trade_name}'")

        trade = self._find_trade_by_name(trade_name)
        if not trade:
            return {"error": f"Препарат '{trade_name}' не найден"}

        # Получаем МНН и фармгруппу
        inter = self.cursor.execute(
            "SELECT INTER_RFN, PHAGRP_ID FROM INTER WHERE INTER_ID = ?",
            (trade['INTER_ID'],)
        ).fetchone()

        pharmgrp_name = None
        if inter:
            grp = self.cursor.execute(
                "SELECT PHAGRP_NAM FROM PHARMGRP WHERE PHAGRP_ID = ?",
                (inter['PHAGRP_ID'],)
            ).fetchone()
            pharmgrp_name = grp['PHAGRP_NAM'] if grp else None

        # Поиск возможных побочных эффектов по фармгруппе (упрощённо)
        # В реальной системе здесь должен быть запрос к таблице побочных эффектов
        side_effects = [
            "Аллергические реакции",
            "Тошнота",
            "Головная боль",
            "Головокружение",
            "Нарушения сна",
            "Повышение артериального давления",
            "Нарушения со стороны ЖКТ",
            "Кожные реакции"
        ]

        return {
            "trade_name": trade['TRADE_RFN'],
            "mnn": inter['INTER_RFN'] if inter else None,
            "pharm_group": pharmgrp_name,
            "possible_side_effects": side_effects,
            "warning": "Список побочных эффектов является ознакомительным. Полный перечень смотрите в официальной инструкции."
        }

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

class DrugFullInfoHandler(BaseQueryHandler):
    """Обработчик: полная информация о препарате."""

    def can_handle(self, intent: str) -> bool:
        return intent == "get_drug_info"

    def handle(self, entities: Dict[str, Any], db_manager: DataBaseManager) -> Dict[str, Any]:
        drug_name = entities.get("drug_name") or entities.get("drug")
        if not drug_name:
            return {"error": "Не указано название препарата"}
        return db_manager.get_drug_full_info(drug_name)


class FindSynonymsHandler(BaseQueryHandler):
    """Обработчик: поиск синонимов по МНН."""

    def can_handle(self, intent: str) -> bool:
        return intent == "find_synonyms"

    def handle(self, entities: Dict[str, Any], db_manager: DataBaseManager) -> Dict[str, Any]:
        mnn = entities.get("mnn") or entities.get("drug_name") or entities.get("substance")
        if not mnn:
            return {"error": "Не указано МНН (действующее вещество)"}
        synonyms = db_manager.get_synonyms_by_mnn(mnn)
        return {
            "intent": "find_synonyms",
            "query": mnn,
            "count": len(synonyms),
            "result": [s['TRADE_RFN'] for s in synonyms]
        }

class FindAnalogsHandler(BaseQueryHandler):
    """Обработчик: поиск аналогов препарата (с возможными фильтрами)."""
    def can_handle(self, intent: str) -> bool:
        return intent == "find_analog"

    def handle(self, entities: Dict[str, Any], db_manager: DataBaseManager) -> Dict[str, Any]:
        drug_name = entities.get("drug_name") or entities.get("drug")
        if not drug_name:
            return {"error": "Не указано название препарата"}

        # 1. Получаем базовый список аналогов и синонимов
        result = db_manager.get_analogs_by_drug(drug_name)
        if "error" in result:
            return result

        # 2. Если есть фильтры, фильтруем
        filters_applied = []
        # Фильтр по дозировке
        if "dosage_value" in entities:
            dosage = entities.get("dosage_value")
            unit = entities.get("unit")
            operator = entities.get("dosage_operator")  # пока не используется
            # Получаем список препаратов с подходящей дозировкой
            dosage_result = db_manager.search_drugs_by_dosage(dosage, unit)
            dosage_drugs = {d.get("TRADE_RFN") for d in dosage_result.get("drugs", []) if d.get("TRADE_RFN")}
            # Пересекаем с нашим списком аналогов + синонимов
            synonyms = set(result.get("synonyms", []))
            analogs = {a["trade"] for a in result.get("analogs", [])}
            # Оставляем только те, что есть в dosage_drugs
            result["synonyms"] = [s for s in synonyms if s in dosage_drugs]
            result["analogs"] = [a for a in result["analogs"] if a["trade"] in dosage_drugs]
            filters_applied.append(f"дозировка {dosage} {unit or ''}")

        # Фильтр по производителю
        if "manufacturer" in entities:
            man = entities["manufacturer"]
            man_result = db_manager.search_drugs_by_manufacturer(man)
            man_drugs = {d.get("TRADE_RFN") for d in man_result.get("drugs", []) if d.get("TRADE_RFN")}
            result["synonyms"] = [s for s in result.get("synonyms", []) if s in man_drugs]
            result["analogs"] = [a for a in result.get("analogs", []) if a["trade"] in man_drugs]
            filters_applied.append(f"производитель {man}")

        # Фильтр по стране
        if "country" in entities:
            cnt = entities["country"]
            cnt_result = db_manager.search_drugs_by_country(cnt)
            cnt_drugs = {d.get("TRADE_RFN") for d in cnt_result.get("drugs", []) if d.get("TRADE_RFN")}
            result["synonyms"] = [s for s in result.get("synonyms", []) if s in cnt_drugs]
            result["analogs"] = [a for a in result.get("analogs", []) if a["trade"] in cnt_drugs]
            filters_applied.append(f"страна {cnt}")

        # Фильтр по форме
        if "form" in entities:
            frm = entities["form"]
            frm_result = db_manager.search_drugs_by_form(frm)
            frm_drugs = {d.get("TRADE_RFN") for d in frm_result.get("drugs", []) if d.get("TRADE_RFN")}
            result["synonyms"] = [s for s in result.get("synonyms", []) if s in frm_drugs]
            result["analogs"] = [a for a in result.get("analogs", []) if a["trade"] in frm_drugs]
            filters_applied.append(f"форма {frm}")

        # Добавляем информацию о применённых фильтрах
        if filters_applied:
            result["filters_applied"] = filters_applied
            result["intent"] = "find_analog"

        return result

class ManufacturerFilterHandler(BaseQueryHandler):
    def can_handle(self, intent: str) -> bool:
        return intent == "filter_by_manufacturer"

    def handle(self, entities, db_manager):
        firm = entities.get("manufacturer") or entities.get("firm")
        if not firm:
            return {"error": "Не указан производитель"}
        return db_manager.search_drugs_by_manufacturer(firm)

class CountryFilterHandler(BaseQueryHandler):
    def can_handle(self, intent: str) -> bool:
        return intent == "filter_by_country"

    def handle(self, entities, db_manager):
        country = entities.get("country")
        if not country:
            return {"error": "Не указана страна"}
        return db_manager.search_drugs_by_country(country)

class FormFilterHandler(BaseQueryHandler):
    def can_handle(self, intent: str) -> bool:
        return intent == "filter_by_form"

    def handle(self, entities, db_manager):
        form = entities.get("form") or entities.get("drug_form")
        if not form:
            return {"error": "Не указана лекарственная форма"}
        return db_manager.search_drugs_by_form(form)

class DosageFilterHandler(BaseQueryHandler):
    def can_handle(self, intent: str) -> bool:
        return intent == "filter_by_dosage"

    def handle(self, entities, db_manager):
        try:
            value = float(entities.get("dosage_value"))
        except (TypeError, ValueError):
            return {"error": "Некорректное числовое значение дозировки"}
        unit = entities.get("unit")  # может отсутствовать
        return db_manager.search_drugs_by_dosage(value, unit)

class CompareDrugsHandler(BaseQueryHandler):
    """Обработчик: сравнение двух препаратов."""
    def can_handle(self, intent: str) -> bool:
        return intent == "compare_drugs"

    def handle(self, entities, db_manager):
        drug1 = entities.get("drug_name")
        drug2 = entities.get("drug_name2")
        if not drug1 or not drug2:
            return {"error": "Укажите два препарата для сравнения"}
        return db_manager.compare_drugs(drug1, drug2)


class InteractionCheckHandler(BaseQueryHandler):
    """Обработчик: проверка взаимодействия препаратов."""
    def can_handle(self, intent: str) -> bool:
        return intent == "check_interaction"

    def handle(self, entities, db_manager):
        drug1 = entities.get("drug_name")
        drug2 = entities.get("drug_name2")
        if not drug1 or not drug2:
            return {"error": "Укажите два препарата для проверки взаимодействия"}
        return db_manager.check_drug_interaction(drug1, drug2)


class SideEffectsHandler(BaseQueryHandler):
    """Обработчик: побочные эффекты препарата."""
    def can_handle(self, intent: str) -> bool:
        return intent == "get_side_effects"

    def handle(self, entities, db_manager):
        drug = entities.get("drug_name") or entities.get("drug")
        if not drug:
            return {"error": "Не указано название препарата"}
        return db_manager.get_drug_side_effects(drug)

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
            DrugFullInfoHandler(),
            FindSynonymsHandler(),
            FindAnalogsHandler(),
            ManufacturerFilterHandler(),
            CountryFilterHandler(),
            FormFilterHandler(),
            DosageFilterHandler(),
            CompareDrugsHandler(),
            InteractionCheckHandler(),
            SideEffectsHandler(),
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

    def process_raw_query(self, user_text: str) -> Dict[str, Any]:
        """
        Принимает сырой текст от пользователя, разбирает его через QueryParser
        и передаёт в process_query.

        Это единая точка входа для GUI.
        """
        parser = QueryParser()
        parsed = parser.parse_query(user_text)

        if parsed.get("error"):
            return parsed

        intent = parsed.get("intent")
        entities = parsed.get("entities", {})

        self.logger.info(f"Разобран запрос: intent='{intent}', entities={entities}")
        return self.process_query(intent, entities)

# ============= БЛОК ТЕСТИРОВАНИЯ =============
# if __name__ == "__main__":
#     logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
#     logger = logging.getLogger(__name__)
#
#     print("=" * 60)
#     print("ТЕСТИРОВАНИЕ ЯДРА АГЕНТА И МЕНЕДЖЕРА БД")
#     print("=" * 60)
#
#     DBF_FOLDER = "egk_extend306"
#     db_manager = DataBaseManager()
#
#     try:
#         logger.info("Инициализация БД (создание таблиц и импорт)...")
#         db_manager.initialize_database(DBF_FOLDER)
#         logger.info("База данных готова к работе.")
#
#         existing_tables = db_manager.cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
#         logger.info(f"Таблиц в БД: {len(existing_tables)}")
#         for t in existing_tables:
#             logger.info(f"  - {t['name']}")
#
#         agent = AgentCore(db_manager)
#
#         # Список тестов: описание, intent, entities
#         tests = [
#             ("Поиск лекарств по болезни", "find_drug_by_disease", {"disease": "Грипп"}),
#             ("Полная информация о препарате", "get_drug_info", {"drug_name": "Анальгин"}),
#             ("Синонимы по МНН", "find_synonyms", {"mnn": "Парацетамол"}),
#             ("Аналоги препарата", "find_analog", {"drug": "Нурофен"}),
#             ("Фильтр по производителю", "filter_by_manufacturer", {"manufacturer": "Байер"}),
#             ("Фильтр по стране", "filter_by_country", {"country": "Германия"}),
#             ("Фильтр по лекарственной форме", "filter_by_form", {"form": "таблетки"}),
#             ("Фильтр по дозировке (500 мг)", "filter_by_dosage", {"dosage_value": "500", "unit": "мг"}),
#             ("Фильтр по дозировке без единицы", "filter_by_dosage", {"dosage_value": "500"}),
#         ]
#
#         for desc, intent, entities in tests:
#             print(f"\n{'=' * 40}")
#             print(f"Тест: {desc}")
#             print(f"Intent: {intent}, Entities: {entities}")
#             print("-" * 30)
#             response = agent.process_query(intent, entities)
#             print("Результат:")
#             print(json.dumps(response, ensure_ascii=False, indent=2))
#
#         # ========== ТЕСТИРОВАНИЕ НОВЫХ МЕТОДОВ ==========
#         print("\n" + "=" * 60)
#         print("ТЕСТИРОВАНИЕ РАСШИРЕННОГО ФУНКЦИОНАЛА")
#         print("=" * 60)
#
#         # Тест сравнения препаратов
#         print("\n=== Тест: Сравнение препаратов ===")
#         resp = agent.process_query("compare_drugs", {"drug_name": "Анальгин", "drug_name2": "Парацетамол"})
#         print(json.dumps(resp, ensure_ascii=False, indent=2))
#
#         # Тест проверки взаимодействия
#         print("\n=== Тест: Проверка взаимодействия ===")
#         resp = agent.process_query("check_interaction", {"drug_name": "Аспирин", "drug_name2": "Ибупрофен"})
#         print(json.dumps(resp, ensure_ascii=False, indent=2))
#
#         # Тест побочных эффектов
#         print("\n=== Тест: Побочные эффекты ===")
#         resp = agent.process_query("get_side_effects", {"drug_name": "Анальгин"})
#         print(json.dumps(resp, ensure_ascii=False, indent=2))
#
#         test_text = "Найди мне аналоги Флебодии"
#         parser = QueryParser()
#         parsed = parser.parse_query(test_text)
#         print("QueryParser:", parsed)
#         if "error" not in parsed and "warning" not in parsed:
#             response = agent.process_query(parsed["intent"], parsed["entities"])
#             print("AgentCore response:")
#             print(json.dumps(response, ensure_ascii=False, indent=2))
#
#     except FileNotFoundError as e:
#         logger.error(f"Критическая ошибка: {e}")
#         print("Поместите DBF-файлы в папку egk_extend306.")
#     except Exception as e:
#         logger.exception("Непредвиденная ошибка")
#     finally:
#         if db_manager:
#             db_manager.close()