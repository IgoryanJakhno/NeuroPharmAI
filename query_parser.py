"""
Модуль QueryParser (Парсер №1) — разбор пользовательских запросов на естественном русском языке.

Реализует:
- Очистку и валидацию запроса
- Поиск ключевых слов-триггеров и определение намерения (intent)
- Извлечение сущностей (названия препаратов, болезней, параметров фильтрации)
- Лемматизацию токенов для приведения к нормальной форме
- Логирование всех действий в консоль

Соответствует пунктам ТЗ: 4.4, 4.16.1, 5.1.6.2
"""

import re
import logging
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime

# --- 1. Инициализация NLP-инструментов ---
# Библиотеки pymorphy2/natasha конфликтуют с новыми версиями Python,
# поэтому лемматизацию будем делать упрощённо, через стоп-слова и регулярные выражения.

# --- 2. Константы и словари ключевых слов ---

# Словарь ключевых слов-триггеров и соответствующих intent
INTENT_TRIGGERS = {
    "find_drug_by_disease": [
        "найти от болезни", "препарат от болезни", "что принимать при",
        "препараты от", "лечение", "болезнь", "заболевание",
        "чем лечить", "терапия", "симптом", "средство от",
        "лекарство от", "таблетки от"
    ],
    "get_drug_info": [
        "информация о препарате", "подробнее о", "описание",
        "что такое", "свойства", "инструкция", "аннотация",
        "подробная информация", "расскажи о", "характеристика"
    ],
    "find_synonyms": [
        "синоним", "дженерик", "синонимы", "то же что",
        "другие названия", "торговые названия", "то же самое",
        "восстановленный", "бренды", "как еще называется",
        "международное название", "мнн"
    ],
    "find_analog": [
        "аналог", "аналоги", "замена", "заменитель",
        "чем заменить", "похожий препарат", "схожий",
        "альтернатива", "подобный", "вместо"
    ],
    "filter_by_manufacturer": [
        "производитель", "фирма", "компания", "лаборатория",
        "фармкомпания", "выпускает", "бренд", "завод",
        "производства", "производит"
    ],
    "filter_by_country": [
        "страна", "производство в", "сделано в",
        "страна производства", "происхождение", "в какой стране"
    ],
    "filter_by_form": [
        "форма выпуска", "форма", "таблетки", "капсулы",
        "сироп", "мазь", "раствор", "спрей", "гель",
        "суспензия", "порошок", "капли", "свечи",
        "лекарственная форма", "в виде"
    ],
    "filter_by_dosage": [
        "дозировка", "доза", "концентрация", "мг", "мл",
        "грамм", "микрограмм", "ме", "международных единиц"
    ],
    "check_interaction": [
        "совместимость", "можно ли вместе", "взаимодействие",
        "можно ли принимать", "одновременно", "вместе",
        "сочетание", "совместный прием", "можно ли совмещать",
        "можно ли пить", "опасно ли"
    ],
    "compare_drugs": [
        "сравни", "сравнение", "что лучше", "что эффективнее",
        "что дешевле", "отличие", "разница", "отличается",
        "сопоставление", "vs"
    ],
}

# Единицы измерения дозировки
DOSAGE_UNITS = [
    "мг", "мл", "г", "грамм", "микрограмм", "мкг",
    "ме", "международных единиц", "ед", "единиц"
]

# Операторы сравнения для дозировки
DOSAGE_OPERATORS = {
    "до": "lte",
    "не более": "lte",
    "менее": "lt",
    "меньше": "lt",
    "от": "gte",
    "не менее": "gte",
    "более": "gt",
    "больше": "gt",
    "ровно": "eq",
    "точно": "eq",
    "равно": "eq",
    "около": "approx",
    "примерно": "approx",
}

# Стоп-слова, которые игнорируются при извлечении сущностей
STOP_WORDS = {
    "найди", "найти", "покажи", "подскажи", "расскажи",
    "хочу", "нужно", "надо", "мне", "для", "это",
    "какой", "какая", "какие", "есть", "будет",
    "пожалуйста", "спасибо", "привет", "помоги",
    "давай", "можешь", "можно", "ли", "все",
    "еще", "очень", "быстро", "срочно"
}


class QueryParser:
    """
    Парсер №1 — анализатор пользовательских запросов на естественном языке.

    Атрибуты:
        logger: Логгер для записи действий в консоль.

    Методы:
        parse_query(user_text: str) -> Dict[str, Any]
            Основной метод: принимает сырой текст, возвращает intent и entities.
    """

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.max_query_length = 500  # согласно ТЗ п. 5.1.2

    def parse_query(self, user_text: str) -> Dict[str, Any]:
        """
        Основной метод разбора пользовательского запроса.

        Args:
            user_text: Сырой текст запроса на русском языке.

        Returns:
            Dict с ключами:
                - intent (str): определённое намерение (например, "find_analog")
                - entities (Dict): извлечённые сущности
                - error (str, optional): сообщение об ошибке, если запрос некорректен
        """
        start_time = datetime.now()
        self.logger.info(f"QueryParser: Получен запрос: '{user_text}'")

        # 1. Валидация и очистка
        clean_text = self._validate_and_clean(user_text)
        if clean_text is None:
            return {"error": "Некорректный запрос. Введите осмысленный текст."}

        # 2. Лемматизация и токенизация
        tokens = self._tokenize_and_lemmatize(clean_text)
        self.logger.info(f"QueryParser: Токены после лемматизации: {tokens}")

        # 3. Поиск ключевых слов-триггеров и определение intent
        intent = self._detect_intent(clean_text, tokens)
        if not intent:
            self.logger.warning("QueryParser: Не удалось определить намерение")
            return {"error": "Не удалось понять запрос. Уточните, что вы хотите найти."}

        self.logger.info(f"QueryParser: Определён intent: {intent}")

        # 4. Извлечение сущностей
        entities = self._extract_entities(clean_text, tokens, intent)
        self.logger.info(f"QueryParser: Извлечены сущности: {entities}")

        # 5. Проверка, что извлечены необходимые сущности для данного intent
        required = self._get_required_entities(intent)
        missing = [e for e in required if e not in entities or not entities[e]]
        if missing:
            self.logger.warning(f"QueryParser: Не хватает сущностей: {missing}")
            return {
                "intent": intent,
                "entities": entities,
                "warning": f"Уточните: {', '.join(missing)}"
            }

        elapsed = (datetime.now() - start_time).total_seconds()
        self.logger.info(f"QueryParser: Разбор завершён за {elapsed:.3f} сек")

        return {
            "intent": intent,
            "entities": entities
        }

    def _validate_and_clean(self, text: str) -> Optional[str]:
        """
        Проверка корректности ввода и очистка.

        Returns:
            Очищенный текст или None, если запрос некорректен.
        """
        if not text or not text.strip():
            self.logger.warning("QueryParser: Пустой запрос")
            return None

        text = text.strip()

        # Проверка длины (не более 500 символов согласно ТЗ)
        if len(text) > self.max_query_length:
            self.logger.warning(f"QueryParser: Запрос слишком длинный ({len(text)} символов)")
            text = text[:self.max_query_length]

        # Удаление специальных символов (оставляем буквы, цифры, пробелы, знаки пунктуации)
        text = re.sub(r'[^\w\s\-\.,!?%()]', '', text)

        # Проверка, что запрос содержит осмысленный текст (не только цифры или спецсимволы)
        if not re.search(r'[а-яА-Яa-zA-Z]', text):
            self.logger.warning("QueryParser: Запрос не содержит букв")
            return None

        # Проверка минимальной длины (хотя бы 2 символа)
        if len(text.replace(' ', '')) < 2:
            self.logger.warning("QueryParser: Слишком короткий запрос")
            return None

        return text

    def _tokenize_and_lemmatize(self, text: str) -> List[str]:
        """
        Упрощённая токенизация и лемматизация без внешних NLP-библиотек.
        """
        # Удаляем знаки препинания и приводим к нижнему регистру
        clean_text = re.sub(r'[^\w\s]', ' ', text).lower()
        tokens = clean_text.split()

        # Убираем стоп-слова и короткие токены
        meaningful_tokens = [t for t in tokens if t not in STOP_WORDS and len(t) > 1]

        return meaningful_tokens

    def _detect_intent(self, clean_text: str, tokens: List[str]) -> Optional[str]:
        """
        Определение намерения пользователя по ключевым словам-триггерам.
        Все intent'ы равноправны, побеждает набравший наибольший вес.
        Порог срабатывания – 3 балла.
        """
        text_lower = clean_text.lower()
        candidates = []

        for intent, triggers in INTENT_TRIGGERS.items():
            score = 0
            for trigger in triggers:
                # Полное совпадение фразы (наибольший вес)
                if trigger in text_lower:
                    score += 5
                else:
                    # Совпадение всех слов триггера в тексте (средний вес)
                    trigger_words = trigger.split()
                    if all(word in tokens for word in trigger_words):
                        score += 3
                    else:
                        # Совпадение отдельных слов (минимальный вес)
                        for word in trigger_words:
                            if word in tokens:
                                score += 1
            if score >= 3:  # Порог уверенности
                candidates.append((intent, score))

        if not candidates:
            # Если ничего не подошло, пробуем угадать по наличию сущностей
            if self._extract_drug_name(clean_text, tokens):
                return "get_drug_info"
            return None

        # Сортируем по убыванию очков, выбираем лучший
        candidates.sort(key=lambda x: x[1], reverse=True)
        self.logger.info(f"QueryParser: Кандидаты intent: {candidates}")
        return candidates[0][0]

    def _extract_entities(self, clean_text: str, tokens: List[str], intent: str) -> Dict[str, Any]:
        entities = {}
        text_lower = clean_text.lower()

        # Универсальное извлечение параметров фильтрации (для всех intent)
        dosage_info = self._extract_dosage_info(clean_text, tokens)
        if dosage_info:
            entities.update(dosage_info)

        manufacturer = self._extract_entity_by_pattern(clean_text, tokens,
                                                       r'(?:производител[ья]|фирм[аы]|компани[ия]|лаборатори[ия])\s+([\w\s\-]+)')
        if manufacturer:
            entities["manufacturer"] = self._clean_entity(manufacturer).capitalize()

        country = self._extract_entity_by_pattern(clean_text, tokens,
                                                  r'(?:стран[аеы]|производств[ао] в|сделано в|производятся в)\s+([\w\s\-]+)')
        if country:
            entities["country"] = self._clean_entity(country).capitalize()

        form = self._extract_entity_by_pattern(clean_text, tokens,
                                               r'(?:форм[аы]|в виде)\s+([\w\s\-]+)')
        if form:
            entities["form"] = self._clean_entity(form).capitalize()

        # --- Извлечение основных сущностей в зависимости от intent ---
        if intent in ("find_analog", "find_synonyms", "get_drug_info"):
            drug = self._extract_drug_name_clean(clean_text, tokens)
            if drug and not drug.replace('.', '').isdigit():  # игнорируем чистые числа
                entities["drug_name"] = drug.capitalize()
            else:
                # Fallback: попробуем найти любое длинное слово, не число и не стоп-слово
                for word in reversed(tokens):
                    if word.lower() not in STOP_WORDS and len(word) > 2 and not word.isdigit():
                        entities["drug_name"] = word.capitalize()
                        break

        elif intent == "find_drug_by_disease":
            disease = self._extract_disease_name_clean(clean_text, tokens)
            if disease:
                entities["disease"] = disease.capitalize()

        elif intent == "compare_drugs":
            # Разделяем по "и", "или", "vs", "против"
            parts = re.split(r'\s+(?:и|или|vs|против)\s+', clean_text)
            # Очищаем первый элемент от командных слов
            first_part = re.sub(r'^(сравни|сравнение|сопоставь|что лучше|что эффективнее|сравниваем)\s+', '',
                                parts[0].strip(), flags=re.I)
            first_part = self._clean_entity(first_part)
            if len(parts) >= 2:
                second_part = self._clean_entity(parts[1])
                if first_part and second_part:
                    entities["drug_name"] = first_part.capitalize()
                    entities["drug_name2"] = second_part.capitalize()
            else:
                drug = self._extract_drug_name_clean(clean_text, tokens)
                if drug:
                    entities["drug_name"] = drug.capitalize()


        elif intent == "check_interaction":

            # Разделяем по "и", "вместе с", "совместно с", "одновременно с"

            parts = re.split(r'\s+(?:и|вместе с|совместно с|одновременно с)\s+', clean_text)

            if len(parts) >= 2:

                # Очищаем первую часть от возможных вводных фраз

                drug1 = re.sub(r'^(можно ли принимать|можно ли совмещать|можно ли пить|можно ли)\s+', '',
                               parts[0].strip(), flags=re.I)

                drug1 = self._clean_entity(drug1)

                drug2 = self._clean_entity(parts[1])

                # Убираем конечные слова-связки: "вместе", "совместно", "одновременно"

                drug2 = re.sub(r'\s+(вместе|совместно|одновременно)\s*$', '', drug2, flags=re.I).strip()

                drug2 = drug2.rstrip('?')

                entities["drug_name"] = drug1.capitalize() if drug1 else ""

                entities["drug_name2"] = drug2.capitalize() if drug2 else ""

            else:

                drug = self._extract_drug_name_clean(clean_text, tokens)

                if drug:
                    entities["drug_name"] = drug.capitalize()

        # Пост-очистка всех строковых значений (убираем возможные стоп-слова)
        for key in list(entities.keys()):
            val = entities[key]
            if isinstance(val, str):
                val = self._clean_entity(val)
                if val and val.lower() not in STOP_WORDS:
                    if key in ("drug_name", "drug_name2", "disease", "manufacturer", "country"):
                        val = val.capitalize()
                    entities[key] = val
                else:
                    del entities[key]

        return entities

    # ---------- Вспомогательные улучшенные экстракторы ----------
    def _extract_drug_name_clean(self, text: str, tokens: List[str]) -> Optional[str]:
        """
        Улучшенное извлечение названия препарата.
        Ищет слова с заглавной буквы в исходном тексте, игнорирует цифры и вопросы.
        """
        # Ищем все слова, которые начинались с заглавной буквы в исходном тексте
        # (это хорошие кандидаты на названия препаратов/болезней)
        words = text.split()
        capital_words = []
        for i, w in enumerate(words):
            # Убираем знаки препинания вокруг
            clean_w = w.strip('.,!?()[]{}":;')
            # Пропускаем короткие, числа и слова, не начинающиеся с заглавной буквы
            if len(clean_w) <= 2:
                continue
            if clean_w.isdigit():
                continue
            # Первое слово в запросе может быть с заглавной буквы, но это не препарат
            if i == 0:
                continue
            # Если слово начинается с заглавной буквы, и это не конец предложения
            if clean_w[0].isupper() and clean_w.lower() not in STOP_WORDS:
                capital_words.append(clean_w)

        # Если нашли такие слова, берём первое (обычно одно) и возвращаем очищенным
        if capital_words:
            return self._clean_entity(capital_words[0])

        # Fallback: ищем любое длинное слово, не являющееся стоп-словом или числом
        for w in reversed(words):
            clean_w = w.strip('.,!?()[]{}":;').lower()
            if clean_w in STOP_WORDS or clean_w.isdigit() or len(clean_w) <= 2:
                continue
            return clean_w.capitalize()
        return None

    def _extract_disease_name_clean(self, text: str, tokens: List[str]) -> Optional[str]:
        """Улучшенное извлечение названия болезни."""
        patterns = [
            r'(?:от|при|против|лечени[ея])\s+([\w\s\-]+?)(?:\s*(?:препарат|таблетк|лекарств|средств|$))',
            r'препарат[ыа]?\s+от\s+([\w\s\-]+)',
            r'таблетк[иа]?\s+от\s+([\w\s\-]+)',
        ]
        for pat in patterns:
            match = re.search(pat, text, re.IGNORECASE)
            if match:
                disease = match.group(1).strip()
                disease = self._clean_entity(disease)
                if disease:
                    return disease
        # Fallback: последнее существительное после "от"
        parts = text.split(' от ')
        if len(parts) > 1:
            return self._clean_entity(parts[-1])
        return None

    def _extract_drug_name(self, text: str, tokens: List[str]) -> Optional[str]:
        """
        Извлекает название препарата из текста.
        Ищет слова с большой буквы, которые не являются началом предложения.
        """
        # Ищем слова с заглавной буквы (не в начале предложения)
        words = text.split()
        candidates = []

        for i, word in enumerate(words):
            clean_word = word.strip('.,!?()[]{}"\':;')
            # Слово с большой буквы, не первое в предложении
            if (clean_word and clean_word[0].isupper() and
                    clean_word.lower() not in STOP_WORDS and
                    len(clean_word) > 1):
                # Не является известным городом/страной (упрощённо)
                if not self._is_location(clean_word):
                    candidates.append(clean_word)

        if candidates:
            return ' '.join(candidates[:2])  # берём не более двух слов

        # Если не нашли с большой буквы, ищем последнее существительное не из стоп-слов
        for word in reversed(words):
            clean = word.strip('.,!?()[]{}"\':;').lower()
            if clean not in STOP_WORDS and len(clean) > 2:
                return clean.capitalize()  # ← добавить .capitalize()

        return None

    def _extract_disease_name(self, text: str, tokens: List[str]) -> Optional[str]:
        """
        Извлекает название болезни из текста.
        """
        # Паттерн: "от <болезни>", "при <болезни>", "лечение <болезни>"
        patterns = [
            r'(?:от|при|против)\s+([\w\s]+?)(?:\s*(?:препарат|таблетк|лекарств|средств|$))',
            r'лечени[ея]\s+([\w\s]+?)(?:\s*(?:$))',
            r'(?:болезн[ьи]|заболевани[ея])\s+([\w\s]+?)(?:\s*(?:$))',
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip().strip('.,!?')

        # Если паттерн не сработал, ищем существительное после ключевых слов
        for word in tokens:
            if word not in STOP_WORDS and len(word) > 2:
                # Проверяем, не является ли слово препаратом (упрощённо)
                if not word.endswith(('ин', 'ол', 'ам', 'ил', 'ан', 'ен', 'он')):
                    return word.capitalize()  # ← добавить .capitalize()

        return None

    def _extract_dosage_info(self, text: str, tokens: List[str]) -> Dict[str, Any]:
        """
        Извлекает информацию о дозировке: значение, оператор, единицу измерения.
        """
        result = {}
        text_lower = text.lower()

        # Ищем числовое значение
        dosage_match = re.search(r'(\d+[.,]?\d*)\s*(мг|мл|г|грамм|микрограмм|мкг|ме|ед)?', text_lower)
        if dosage_match:
            value_str = dosage_match.group(1).replace(',', '.')
            try:
                result["dosage_value"] = float(value_str)
            except ValueError:
                pass

            unit = dosage_match.group(2)
            if unit:
                result["unit"] = unit

        # Ищем оператор сравнения
        for op_word, op_code in DOSAGE_OPERATORS.items():
            if op_word in text_lower:
                result["dosage_operator"] = op_code
                break

        return result

    def _extract_entity_by_pattern(self, text: str, tokens: List[str], pattern: str) -> Optional[str]:
        """
        Извлекает сущность по регулярному выражению.
        """
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip().strip('.,!?')
        return None

    def _extract_capitalized_entity(self, tokens: List[str]) -> Optional[str]:
        """Извлекает слово с большой буквы (для производителя, страны и т.д.)."""
        # Упрощённо: вернуть первое слово, не являющееся стоп-словом
        for token in tokens:
            if token not in STOP_WORDS and len(token) > 2:
                return token.capitalize()
        return None

    def _is_location(self, word: str) -> bool:
        """Упрощённая проверка, является ли слово названием страны/города."""
        locations = {
            "россия", "германия", "франция", "индия", "китай", "сша",
            "япония", "швейцария", "великобритания", "италия", "испания",
            "канада", "австралия", "польша", "венгрия", "словения",
            "хорватия", "сербия", "чехия", "словакия", "австрия",
            "бельгия", "нидерланды", "швеция", "норвегия", "дания",
            "финляндия", "израиль", "турция", "бразилия", "мексика"
        }
        return word.lower() in locations

    def _get_required_entities(self, intent: str) -> List[str]:
        """
        Возвращает список обязательных сущностей для данного intent.
        """
        required_map = {
            "find_drug_by_disease": ["disease"],
            "get_drug_info": ["drug_name"],
            "find_synonyms": [],
            "find_analog": ["drug_name"],
            "filter_by_manufacturer": ["manufacturer"],
            "filter_by_country": ["country"],
            "filter_by_form": ["form"],
            "filter_by_dosage": ["dosage_value"],
            "check_interaction": ["drug_name", "drug_name2"],
            "compare_drugs": ["drug_name", "drug_name2"],
        }
        return required_map.get(intent, [])

    def get_intent_list(self) -> List[str]:
        """Возвращает список всех поддерживаемых intent'ов."""
        return list(INTENT_TRIGGERS.keys())

    def _clean_entity(self, text: str) -> str:
        """Удаляет стоп-слова и лишние символы из извлечённой сущности."""
        if not text:
            return text
        # Удаляем знаки препинания, оставляем буквы, цифры, пробелы, дефисы
        text = re.sub(r'[^\w\s\-]', ' ', text)
        # Разбиваем на слова
        words = text.split()
        # Отфильтровываем стоп-слова и слишком короткие токены
        filtered = [w for w in words if w.lower() not in STOP_WORDS and len(w) > 1]
        return ' '.join(filtered).strip()

    @staticmethod
    def export_to_json(filepath: str = "prompt_templates.json") -> None:
        """
        Экспортирует текущие настройки и словари в JSON-файл.
        Используется администратором для синхронизации.
        """
        import json

        data = {
            "_description": "Экспортированные настройки QueryParser",
            "_exported_at": datetime.now().isoformat(),
            "intents": {}
        }

        for intent, triggers in INTENT_TRIGGERS.items():
            data["intents"][intent] = {
                "triggers": triggers,
                "required_entities": QueryParser._get_required_entities_static(intent)
            }

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logging.getLogger(__name__).info(f"Настройки экспортированы в {filepath}")

    @staticmethod
    def _get_required_entities_static(intent: str) -> List[str]:
        """Вспомогательный статический метод для экспорта."""
        required_map = {
            "find_drug_by_disease": ["disease"],
            "get_drug_info": ["drug_name"],
            "find_synonyms": [],
            "find_analog": ["drug_name"],
            "filter_by_manufacturer": ["manufacturer"],
            "filter_by_country": ["country"],
            "filter_by_form": ["form"],
            "filter_by_dosage": ["dosage_value"],
            "check_interaction": ["drug_name", "drug_name2"],
            "compare_drugs": ["drug_name", "drug_name2"],
        }
        return required_map.get(intent, [])

# ============= ТЕСТОВЫЙ БЛОК =============
# if __name__ == "__main__":
#     # Настройка логирования для тестов
#     logging.basicConfig(
#         level=logging.INFO,
#         format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
#     )
#
#     parser = QueryParser()
#
#     test_queries = [
#         "Найди мне аналоги Азитромицина дозировкой до 100 мг",
#         "Чем заменить Нурофен?",
#         "Расскажи подробнее о Парацетамоле",
#         "Какие есть синонимы у Ибупрофена?",
#         "Найди препараты от гриппа",
#         "Покажи лекарства производителя Байер",
#         "Какие препараты производятся в Германии?",
#         "Найди таблетки от головной боли",
#         "Можно ли принимать Аспирин и Ибупрофен вместе?",
#         "Сравни Анальгин и Парацетамол",
#         "Найди препараты с дозировкой 500 мг",
#         "",  # пустой запрос
#         "???"  # некорректный запрос
#     ]
#
#     print("=" * 60)
#     print("ТЕСТИРОВАНИЕ QUERYPARSER (ПАРСЕР №1)")
#     print("=" * 60)
#
#     for query in test_queries:
#         print(f"\nЗапрос: '{query}'")
#         result = parser.parse_query(query)
#         print(f"Результат: {result}")
#         print("-" * 40)
#
#     print("\nПоддерживаемые intent'ы:")
#     for intent in parser.get_intent_list():
#         print(f"  - {intent}")