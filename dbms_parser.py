"""
Модуль DBMSParser (Парсер №2) — формирование структурированных ответов.

Преобразует JSON-ответы от AgentCore/DataBaseManager в человекочитаемый текст
с предустановленными шаблонами для каждого типа запроса.

Соответствует пунктам ТЗ: 4.16.2, 5.1.6.3
"""

import logging
import json
from typing import Dict, Any, List, Optional


class DBMSParser:
    """
    Парсер №2 — формирование структурированных ответов из JSON.

    Атрибуты:
        logger: Логгер для записи действий в консоль.
        disclaimer: Текст дисклеймера, добавляемый ко всем медицинским ответам.
    """

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.disclaimer = (
            "\n\n⚠️ Информация носит справочный характер. "
            "Перед применением проконсультируйтесь с врачом."
        )

    def format_response(self, response: Dict[str, Any]) -> str:
        """
        Основной метод — форматирует JSON-ответ в читаемый текст.
        """
        if "error" in response:
            return self._format_error(response["error"])

        intent = response.get("intent", "")

        formatters = {
            "find_drug_by_disease": self._format_drugs_by_disease,
            "get_drug_info": self._format_drug_full_info,
            "find_synonyms": self._format_synonyms,
            "find_analog": self._format_analogs,
            "filter_by_manufacturer": self._format_filter_by_manufacturer,
            "filter_by_country": self._format_filter_by_country,
            "filter_by_form": self._format_filter_by_form,
            "filter_by_dosage": self._format_filter_by_dosage,
            "compare_drugs": self._format_compare_drugs,
            "check_interaction": self._format_interaction,
            "get_side_effects": self._format_side_effects,
        }

        formatter = formatters.get(intent)
        if formatter:
            result = formatter(response)
            return result + self.disclaimer
        else:
            # Если intent не распознан, пытаемся вывести данные как есть
            if "drug_name" in response:
                return f"Препарат: {response.get('drug_name', '—')}" + self.disclaimer
            elif "disease" in response:
                return f"Заболевание: {response.get('disease', '—')}" + self.disclaimer
            else:
                return f"Результат: {str(response)}" + self.disclaimer

    def _format_error(self, error_msg: str) -> str:
        """Форматирование сообщения об ошибке."""
        return f"❌ {error_msg}"

    def _format_drugs_by_disease(self, data: Dict[str, Any]) -> str:
        """Форматирование результатов поиска препаратов по болезни."""
        disease = data.get("query", "указанное заболевание")
        drugs = data.get("result", [])
        count = data.get("count", len(drugs))

        if count == 0:
            return f"По запросу «{disease}» препаратов не найдено."

        lines = [f"💊 Препараты для лечения «{disease}» (найдено: {count}):\n"]
        for i, drug in enumerate(drugs, 1):
            lines.append(f"{i}. {drug}")

        return "\n".join(lines)

    def _format_drug_full_info(self, data: Dict[str, Any]) -> str:
        """Форматирование полной информации о препарате."""
        trade_name = data.get("trade_name", "Неизвестный препарат")
        mnn = data.get("mnn", "Нет данных")
        packages = data.get("packages", [])
        total = data.get("total_packages", len(packages))

        lines = [
            f"📋 Информация о препарате «{trade_name}»",
            f"• Действующее вещество (МНН): {mnn}",
            f"• Количество упаковок в БД: {total}\n",
        ]

        if packages:
            lines.append("Доступные формы выпуска:")
            for i, pkg in enumerate(packages[:10], 1):
                name = pkg.get("DRUG_NAME", "—")
                dose = pkg.get("MED_DOSE", "")
                form = pkg.get("FORM_RFN", "")
                firm = pkg.get("FIRM_RFN", "")
                country = pkg.get("CNTRY_RFN", "")

                details = []
                if dose:
                    details.append(f"дозировка: {dose}")
                if form:
                    details.append(f"форма: {form}")
                if firm:
                    details.append(f"производитель: {firm}")
                if country:
                    details.append(f"страна: {country}")

                detail_str = ", ".join(details) if details else "нет дополнительных данных"
                lines.append(f"  {i}. {name} ({detail_str})")

            if total > 10:
                lines.append(f"  ... и ещё {total - 10} упаковок")
        else:
            lines.append("Нет данных об упаковках.")

        return "\n".join(lines)

    def _format_synonyms(self, data: Dict[str, Any]) -> str:
        """Форматирование списка синонимов."""
        query = data.get("query", "указанное вещество")
        synonyms = data.get("result", [])
        count = data.get("count", len(synonyms))

        if count == 0:
            return f"Синонимов для «{query}» не найдено."

        lines = [f"💊 Синонимы (торговые названия) для «{query}» (найдено: {count}):\n"]
        for i, syn in enumerate(synonyms, 1):
            lines.append(f"{i}. {syn}")

        return "\n".join(lines)

    def _format_analogs(self, data: Dict[str, Any]) -> str:
        """Форматирование списка аналогов (синонимы + терапевтические аналоги)."""
        drug = data.get("query", data.get("drug", "указанный препарат"))
        synonyms = data.get("synonyms", [])
        analogs = data.get("analogs", [])

        lines = [f"💊 Синонимы и аналоги для «{drug}»:\n"]

        if synonyms:
            lines.append("🔹 Полные аналоги (то же действующее вещество):")
            for i, syn in enumerate(synonyms, 1):
                lines.append(f"  {i}. {syn}")
        else:
            lines.append("🔹 Полные аналоги: не найдены")

        lines.append("")

        if analogs:
            lines.append("🔸 Терапевтические аналоги (та же фармгруппа):")
            for i, analog in enumerate(analogs, 1):
                trade = analog.get("trade", "")
                mnn = analog.get("mnn", "")
                lines.append(f"  {i}. {trade} (МНН: {mnn})")
        else:
            lines.append("🔸 Терапевтические аналоги: не найдены")

        return "\n".join(lines)

    def _format_filter_by_manufacturer(self, data: Dict[str, Any]) -> str:
        """Форматирование результатов фильтрации по производителю."""
        manufacturer = data.get("manufacturer", "указанный производитель")
        drugs = data.get("drugs", [])
        count = data.get("count", len(drugs))

        if count == 0:
            return f"Препаратов производителя «{manufacturer}» не найдено."

        lines = [f"🏭 Препараты производителя «{manufacturer}» (найдено: {count}):\n"]
        for i, drug in enumerate(drugs[:20], 1):
            name = drug.get("TRADE_RFN") or drug.get("DRUG_NAME", "—")
            lines.append(f"{i}. {name}")

        if count > 20:
            lines.append(f"... и ещё {count - 20} препаратов")

        return "\n".join(lines)

    def _format_filter_by_country(self, data: Dict[str, Any]) -> str:
        """Форматирование результатов фильтрации по стране."""
        country = data.get("country", "указанная страна")
        drugs = data.get("drugs", [])
        count = data.get("count", len(drugs))

        if count == 0:
            return f"Препаратов из страны «{country}» не найдено."

        lines = [f"🌍 Препараты из страны «{country}» (найдено: {count}):\n"]
        for i, drug in enumerate(drugs[:20], 1):
            name = drug.get("TRADE_RFN") or drug.get("DRUG_NAME", "—")
            lines.append(f"{i}. {name}")

        if count > 20:
            lines.append(f"... и ещё {count - 20} препаратов")

        return "\n".join(lines)

    def _format_filter_by_form(self, data: Dict[str, Any]) -> str:
        """Форматирование результатов фильтрации по лекарственной форме."""
        form = data.get("form", "указанная форма")
        drugs = data.get("drugs", [])
        count = data.get("count", len(drugs))

        if count == 0:
            return f"Препаратов в форме «{form}» не найдено."

        lines = [f"💊 Препараты в форме «{form}» (найдено: {count}):\n"]
        for i, drug in enumerate(drugs[:20], 1):
            name = drug.get("TRADE_RFN") or drug.get("DRUG_NAME", "—")
            form_name = drug.get("DRUGF_RFN") or drug.get("GENF_RFN", "")
            if form_name:
                lines.append(f"{i}. {name} — {form_name}")
            else:
                lines.append(f"{i}. {name}")

        if count > 20:
            lines.append(f"... и ещё {count - 20} препаратов")

        return "\n".join(lines)

    def _format_filter_by_dosage(self, data: Dict[str, Any]) -> str:
        """Форматирование результатов фильтрации по дозировке."""
        dosage = data.get("dosage", "указанная дозировка")
        drugs = data.get("drugs", [])
        count = data.get("count", len(drugs))

        if count == 0:
            return f"Препаратов с дозировкой «{dosage}» не найдено."

        lines = [f"⚖️ Препараты с дозировкой «{dosage}» (найдено: {count}):\n"]
        for i, drug in enumerate(drugs[:20], 1):
            name = drug.get("TRADE_RFN") or drug.get("DRUG_NAME", "—")
            lines.append(f"{i}. {name}")

        if count > 20:
            lines.append(f"... и ещё {count - 20} препаратов")

        return "\n".join(lines)

    def _format_compare_drugs(self, data: Dict[str, Any]) -> str:
        """Форматирование результатов сравнения двух препаратов."""
        drug1 = data.get("drug1", {})
        drug2 = data.get("drug2", {})
        comparison = data.get("comparison", {})

        lines = [
            f"📊 Сравнение препаратов:\n",
            f"┌─────────────────────────────────────────────────────┐",
            f"│ Препарат 1: {drug1.get('trade_name', '—')}",
            f"│ Препарат 2: {drug2.get('trade_name', '—')}",
            f"├─────────────────────────────────────────────────────┤",
            f"│ МНН:                                                │",
            f"│   • {drug1.get('mnn', '—')}",
            f"│   • {drug2.get('mnn', '—')}",
            f"│   Совпадают: {'✅ Да' if comparison.get('same_mnn') else '❌ Нет'}",
            f"├─────────────────────────────────────────────────────┤",
            f"│ Фармгруппа:                                         │",
            f"│   • {drug1.get('pharm_group', '—')}",
            f"│   • {drug2.get('pharm_group', '—')}",
            f"│   Совпадают: {'✅ Да' if comparison.get('same_pharm_group') else '❌ Нет'}",
            f"├─────────────────────────────────────────────────────┤",
        ]

        common_manufacturers = comparison.get("common_manufacturers", [])
        if common_manufacturers:
            lines.append(f"│ Общие производители: {', '.join(common_manufacturers[:3])}")
        else:
            lines.append("│ Общие производители: отсутствуют")

        common_forms = comparison.get("common_forms", [])
        if common_forms:
            lines.append(f"│ Общие формы выпуска: {', '.join(common_forms[:3])}")
        else:
            lines.append("│ Общие формы выпуска: отсутствуют")

        lines.append("└─────────────────────────────────────────────────────┘")

        return "\n".join(lines)

    def _format_interaction(self, data: Dict[str, Any]) -> str:
        """Форматирование результатов проверки взаимодействия."""
        drug1 = data.get("drug1", "—")
        drug2 = data.get("drug2", "—")
        warnings = data.get("warnings", [])

        lines = [
            f"🔍 Проверка взаимодействия: «{drug1}» и «{drug2}»\n"
        ]

        if warnings:
            for warning in warnings:
                lines.append(f"⚠️ {warning}")
        else:
            lines.append("✅ Данных о взаимодействии не найдено.")

        return "\n".join(lines)

    def _format_side_effects(self, data: Dict[str, Any]) -> str:
        """Форматирование списка побочных эффектов."""
        trade_name = data.get("trade_name", "Неизвестный препарат")
        mnn = data.get("mnn", "Нет данных")
        pharm_group = data.get("pharm_group", "Нет данных")
        side_effects = data.get("possible_side_effects", [])
        warning = data.get("warning", "")

        lines = [
            f"⚠️ Побочные эффекты препарата «{trade_name}»",
            f"• Действующее вещество: {mnn}",
            f"• Фармгруппа: {pharm_group}\n",
            "Возможные побочные эффекты:"
        ]

        for i, effect in enumerate(side_effects, 1):
            lines.append(f"  {i}. {effect}")

        if warning:
            lines.append(f"\n📝 {warning}")

        return "\n".join(lines)

    def format_for_llm(self, response: Dict[str, Any]) -> str:
        """
        Формирует структурированный промпт для передачи в LLM.
        Отличается от format_response тем, что добавляет системные инструкции
        и передает в LLM уже готовый, человекочитаемый ответ.
        """
        # 1. Получаем уже готовый, "человеческий" ответ
        human_readable_answer = self.format_response(response)

        # 2. Формируем промпт для LLM, в который вставляем этот ответ
        llm_prompt = (
            f"Ты — ИИ-ассистент для фармацевтических консультаций.\n"
            f"На основе следующего ответа, который уже был сформирован для пользователя, "
            f"предоставь финальный, понятный ответ на русском языке. "
            f"Сохрани структуру и информативность исходного ответа.\n\n"
            f"Исходный ответ:\n{human_readable_answer}\n\n"
            f"Сформируй финальный ответ."
        )

        return llm_prompt

    def load_disclaimers_from_json(self, filepath: str = "prompt_templates.json") -> None:
        """Загружает дисклеймеры из JSON-файла."""
        import json
        import os

        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                config = json.load(f)
                if "disclaimers" in config:
                    self.disclaimer = config["disclaimers"].get("medical", self.disclaimer)

# ============= ТЕСТОВЫЙ БЛОК =============
# if __name__ == "__main__":
#     # Настройка логирования
#     logging.basicConfig(
#         level=logging.INFO,
#         format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
#     )
#
#     parser = DBMSParser()
#
#     # Тестовые JSON-ответы (симулируют ответы от AgentCore)
#     test_responses = [
#         {
#             "intent": "find_drug_by_disease",
#             "query": "Грипп",
#             "count": 3,
#             "result": ["Терафлю", "Колдрекс", "Антигриппин"]
#         },
#         {
#             "intent": "get_drug_info",
#             "trade_name": "Анальгин",
#             "mnn": "Метамизол натрия",
#             "total_packages": 5,
#             "packages": [
#                 {"DRUG_NAME": "Анальгин таб. 500 мг", "MED_DOSE": "500 мг",
#                  "FORM_RFN": "таблетки", "FIRM_RFN": "Фармстандарт", "CNTRY_RFN": "Россия"}
#             ]
#         },
#         {
#             "intent": "find_synonyms",
#             "query": "парацетамол",
#             "count": 3,
#             "result": ["Панадол", "Эффералган", "Цефекон"]
#         },
#         {
#             "intent": "find_analog",
#             "query": "Нурофен",
#             "synonyms": ["Ибупрофен", "МИГ 400"],
#             "analogs": [
#                 {"trade": "Кеторол", "mnn": "Кеторолак"},
#                 {"trade": "Диклофенак", "mnn": "Диклофенак"}
#             ]
#         },
#         {
#             "intent": "compare_drugs",
#             "drug1": {"trade_name": "Анальгин", "mnn": "Метамизол натрия", "pharm_group": "Анальгетики"},
#             "drug2": {"trade_name": "Парацетамол", "mnn": "Парацетамол", "pharm_group": "Анальгетики"},
#             "comparison": {
#                 "same_mnn": False,
#                 "same_pharm_group": True,
#                 "common_manufacturers": ["Фармстандарт"],
#                 "common_forms": ["таблетки"]
#             }
#         },
#         {
#             "intent": "check_interaction",
#             "drug1": "Аспирин",
#             "drug2": "Ибупрофен",
#             "same_mnn": False,
#             "same_pharm_group": True,
#             "warnings": ["Препараты относятся к одной фармгруппе — риск усиления побочных эффектов."]
#         },
#         {"error": "Препарат не найден"}
#     ]
#
#     print("=" * 60)
#     print("ТЕСТИРОВАНИЕ DBMSPARSER (ПАРСЕР №2)")
#     print("=" * 60)
#
#     for i, response in enumerate(test_responses, 1):
#         print(f"\n{'=' * 40}")
#         print(f"Тест {i}: {response.get('intent', 'error')}")
#         print("-" * 30)
#         formatted = parser.format_response(response)
#         print(formatted)
#
#     print("\n" + "=" * 60)
#     print("ТЕСТИРОВАНИЕ ФОРМИРОВАНИЯ PROMPT ДЛЯ LLM")
#     print("=" * 60)
#     llm_prompt = parser.format_for_llm(test_responses[0])
#     print(llm_prompt)