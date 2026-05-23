"""
Модуль управления LLM (Llama 3.1 через Ollama)

Реализует:
- Подключение к локальному серверу Ollama
- Загрузку и использование Llama 3.1
- Формирование запросов с системным промптом
- Очистку и валидацию выходных данных
- Логирование всех операций

Соответствует пунктам ТЗ: 4.2.4, 4.10, 4.17, 5.1.6.5
"""

import logging
import json
import os
import re
from typing import Optional, Dict, Any, List
from datetime import datetime

import requests  # pip install requests


class LLMManager:
    """
    Менеджер языковой модели Llama 3.1.

    Атрибуты:
        model_name (str): Имя модели в Ollama.
        api_url (str): URL сервера Ollama.
        system_prompt (str): Системный промпт (предустановка).
        max_tokens (int): Максимальная длина выходного текста.
        temperature (float): Параметр температуры генерации.
        templates (Dict): Словарь шаблонов промтов из JSON.
        logger: Логгер.
    """

    def __init__(
            self,
            model_name: str = "llama3.1:8b",
            api_url: str = "http://localhost:11434/api/generate",
            templates_path: str = "prompt_templates.json",
            max_tokens: int = 1024,
            temperature: float = 0.7,
            timeout: int = 120
    ):
        self.model_name = model_name
        self.api_url = api_url
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout = timeout
        self.logger = logging.getLogger(__name__)

        # Системный промпт согласно ТЗ (п. 5.1.6.5)
        self.system_prompt = (
            "Ты — ИИ-ассистент для фармацевтических консультаций. "
            "Твоя задача — предоставлять точную, структурированную информацию "
            "о лекарственных препаратах, их аналогах, показаниях и противопоказаниях. "
            "Отвечай только по существу запроса. "
            "Используй структурированные ответы с четким форматированием. "
            "Всегда добавляй предупреждение: 'Информация носит справочный характер. "
            "Перед применением проконсультируйтесь с врачом.'"
        )

        # Загружаем шаблоны промтов
        self.templates = self._load_templates(templates_path)

        self.logger.info(f"LLMManager инициализирован: model={model_name}, timeout={timeout}с")

    def _load_templates(self, templates_path: str) -> Dict[str, Any]:
        """
        Загрузка словаря шаблонов промтов из JSON.
        """
        if os.path.exists(templates_path):
            try:
                with open(templates_path, 'r', encoding='utf-8') as f:
                    templates = json.load(f)
                    self.logger.info(f"Шаблоны загружены из {templates_path}")
                    return templates
            except json.JSONDecodeError as e:
                self.logger.error(f"Ошибка чтения JSON шаблонов: {e}")
        else:
            self.logger.warning(f"Файл шаблонов {templates_path} не найден, использую пустой словарь")
        return {}

    def generate_response(self, user_prompt: str, system_prompt: Optional[str] = None) -> Optional[str]:
        """
        Отправка запроса к Llama и получение ответа.

        Args:
            user_prompt: Текст запроса пользователя (или формуляр от DBMSParser).
            system_prompt: Переопределение системного промпта (если нужно).

        Returns:
            Ответ модели или None в случае ошибки.
        """
        system = system_prompt if system_prompt else self.system_prompt

        # Формируем полный промпт
        full_prompt = f"{system}\n\n{user_prompt}"

        payload = {
            "model": self.model_name,
            "prompt": full_prompt,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.max_tokens
            }
        }

        self.logger.info(f"Отправка запроса к LLM (модель: {self.model_name})")
        start_time = datetime.now()

        try:
            response = requests.post(
                self.api_url,
                json=payload,
                timeout=self.timeout
            )
            response.raise_for_status()

            result = response.json()
            raw_text = result.get("response", "")

            elapsed = (datetime.now() - start_time).total_seconds()
            self.logger.info(f"Ответ от LLM получен за {elapsed:.2f} сек, длина: {len(raw_text)} символов")

            # Очистка и валидация
            cleaned = self._clean_output(raw_text)

            if not self._validate_output(cleaned):
                self.logger.warning("Выходные данные не прошли валидацию, возвращаю как есть")
                return cleaned

            return cleaned

        except requests.exceptions.Timeout:
            self.logger.error(f"Таймаут запроса к LLM (>{self.timeout}с)")
            return None
        except requests.exceptions.ConnectionError:
            self.logger.error("Не удалось подключиться к Ollama. Проверьте, что сервер запущен (ollama serve)")
            return None
        except Exception as e:
            self.logger.error(f"Ошибка при запросе к LLM: {e}")
            return None

    def generate_with_template(self, template_key: str, **kwargs) -> Optional[str]:
        """
        Генерация ответа с использованием шаблона промпта.

        Args:
            template_key: Ключ шаблона в словаре templates.
            **kwargs: Параметры для подстановки в шаблон.

        Returns:
            Ответ модели или None.
        """
        template = self.templates.get(template_key)
        if not template:
            self.logger.warning(f"Шаблон '{template_key}' не найден")
            return None

        # Простая подстановка параметров в шаблон
        prompt = template
        for key, value in kwargs.items():
            placeholder = "{" + key + "}"
            prompt = prompt.replace(placeholder, str(value))

        return self.generate_response(prompt)

    def analyze_with_context(self, dbms_result: Dict[str, Any]) -> Optional[str]:
        """
        Расширенный анализ с использованием результата от DBMSParser.
        Вызывает format_for_llm для получения формуляра и отправляет его в Llama.

        Args:
            dbms_result: Структурированный результат от AgentCore.

        Returns:
            Ответ Llama в читаемом виде.
        """
        # Импортируем DBMSParser здесь, чтобы избежать циклических импортов
        from dbms_parser import DBMSParser

        parser = DBMSParser()
        llm_prompt = parser.format_for_llm(dbms_result)

        self.logger.info("Анализ с контекстом через DBMSParser")
        return self.generate_response(llm_prompt)

    def _clean_output(self, text: str) -> str:
        """
        Очистка выходных данных от опасных символов и лишних пробелов.
        """
        if not text:
            return ""

        # Удаляем потенциально опасные символы (SQL-инъекции, HTML-теги)
        text = re.sub(r'<[^>]+>', '', text)  # убираем HTML-теги
        text = re.sub(r'[`\'"]', '', text)  # убираем кавычки (для безопасности)

        # Убираем множественные пробелы и переносы строк
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r' {2,}', ' ', text)

        return text.strip()

    def _validate_output(self, text: str) -> bool:
        """
        Проверка выходных данных на наличие осмысленной информации.
        """
        if not text or len(text) < 10:
            self.logger.warning("Выходной текст слишком короткий")
            return False

        # Проверяем, что текст содержит буквы (не только цифры и символы)
        if not re.search(r'[а-яА-Яa-zA-Z]', text):
            self.logger.warning("Выходной текст не содержит букв")
            return False

        return True

    def trim_response(self, text: str, max_length: int = 2000) -> str:
        """
        Обрезка ответа при превышении лимита буфера.
        """
        if len(text) > max_length:
            self.logger.warning(f"Ответ обрезан до {max_length} символов")
            return text[:max_length] + "...\n(ответ сокращён)"
        return text

    def check_availability(self) -> bool:
        """
        Проверка доступности сервера Ollama.
        """
        try:
            response = requests.get("http://localhost:11434/api/tags", timeout=5)
            if response.status_code == 200:
                models = response.json().get("models", [])
                model_names = [m["name"] for m in models]
                self.logger.info(f"Доступные модели в Ollama: {model_names}")
                return self.model_name in model_names
            return False
        except Exception as e:
            self.logger.error(f"Сервер Ollama недоступен: {e}")
            return False

    def get_model_info(self) -> Optional[Dict[str, Any]]:
        """
        Получение информации о загруженной модели.
        """
        try:
            response = requests.post(
                "http://localhost:11434/api/show",
                json={"name": self.model_name},
                timeout=10
            )
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            self.logger.error(f"Ошибка получения информации о модели: {e}")
        return None


# ============= ТЕСТОВЫЙ БЛОК =============
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    print("=" * 60)
    print("ТЕСТИРОВАНИЕ LLM MANAGER")
    print("=" * 60)

    llm = LLMManager()

    # Проверка доступности
    print("\n1. Проверка доступности Ollama...")
    if llm.check_availability():
        print(f"✅ Модель '{llm.model_name}' доступна")
    else:
        print(f"❌ Модель '{llm.model_name}' не найдена. Запустите 'ollama run llama3.1:8b'")

    # Тестовый запрос
    print("\n2. Тестовый запрос к Llama...")
    test_prompt = "Расскажи кратко, что такое парацетамол и для чего он применяется."
    response = llm.generate_response(test_prompt)

    if response:
        print(f"✅ Ответ получен ({len(response)} символов):")
        print("-" * 40)
        print(llm.trim_response(response, 500))
    else:
        print("❌ Не удалось получить ответ от LLM")

    # Тест с шаблоном
    print("\n3. Тест с использованием шаблона...")
    if llm.templates:
        print(f"Доступные шаблоны: {list(llm.templates.keys())}")
    else:
        print("Шаблоны не загружены (файл prompt_templates.json отсутствует)")

    # Тест анализа с контекстом (симуляция)
    print("\n4. Тест анализа с контекстом DBMSParser...")
    mock_result = {
        "intent": "find_analog",
        "query": "Нурофен",
        "synonyms": ["Ибупрофен", "МИГ 400"],
        "analogs": [{"trade": "Кеторол", "mnn": "Кеторолак"}]
    }
    analysis = llm.analyze_with_context(mock_result)
    if analysis:
        print(f"✅ Анализ выполнен ({len(analysis)} символов)")
        print("-" * 40)
        print(llm.trim_response(analysis, 500))
    else:
        print("❌ Не удалось выполнить анализ")