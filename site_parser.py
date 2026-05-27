"""
Модуль SiteParser (Парсер №3) – сбор информации с авторитетного сайта rlsnet.ru.

Соответствует ТЗ п. 4.2.8, 5.1.6.4.
"""

import requests
import logging
import time
from typing import Optional, Dict, Any
from bs4 import BeautifulSoup
from urllib.parse import quote, urljoin


class SiteParser:
    """
    Парсер для получения подробной информации о лекарственных препаратах с rlsnet.ru.

    Атрибуты:
        base_url: Базовый URL сайта.
        search_url: URL поиска.
        headers: Заголовки для имитации браузера.
        timeout: Таймаут ожидания ответа.
        retries: Количество повторных попыток.
        delay: Задержка между запросами (сек).
        logger: Логгер.
    """

    def __init__(self, base_url: str = "https://www.rlsnet.ru", timeout: int = 10, retries: int = 3,
                 delay: float = 1.0):
        self.base_url = base_url
        self.search_url = urljoin(base_url, "/search.htm")
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3",
        }
        self.timeout = timeout
        self.retries = retries
        self.delay = delay
        self.logger = logging.getLogger("NeuroPharm.SiteParser")
        self.session = requests.Session()
        self.session.headers.update(self.headers)

    def _request_with_retry(self, url: str, params: Optional[Dict] = None) -> Optional[requests.Response]:
        """Выполняет HTTP-запрос с повторными попытками."""
        for attempt in range(self.retries):
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
                response.raise_for_status()
                return response
            except requests.exceptions.RequestException as e:
                self.logger.warning(f"Попытка {attempt + 1}/{self.retries} не удалась: {e}")
                if attempt < self.retries - 1:
                    time.sleep(self.delay)
                else:
                    self.logger.error(f"Не удалось получить {url}: {e}")
                    return None
        return None

    def _search_drug(self, drug_name: str) -> Optional[str]:
        """
        Выполняет поиск препарата на сайте и возвращает URL страницы с инструкцией.
        """
        self.logger.info(f"Поиск препарата '{drug_name}' на {self.base_url}")
        params = {"query": drug_name}
        response = self._request_with_retry(self.search_url, params)
        if not response:
            return None

        soup = BeautifulSoup(response.text, 'html.parser')
        # Ищем ссылки, ведущие на страницы препаратов (обычно /drugs/...)
        # Уточнение селекторов может потребоваться после анализа структуры сайта
        links = soup.find_all('a', href=True)
        for link in links:
            href = link['href']
            if '/drugs/' in href and 'инструкция' in link.get_text().lower():
                full_url = urljoin(self.base_url, href)
                self.logger.info(f"Найдена страница препарата: {full_url}")
                return full_url
            # Запасной вариант: первая ссылка с /drugs/
            if '/drugs/' in href and not full_url:
                full_url = urljoin(self.base_url, href)
        if full_url:
            return full_url
        self.logger.warning(f"Не найдена страница препарата для '{drug_name}'")
        return None

    def _extract_instruction_text(self, soup: BeautifulSoup) -> str:
        """
        Извлекает полный текст инструкции из HTML-страницы.
        """
        # Ищем контейнер инструкции – обычно div с классом, содержащим 'instruction' или 'drug-description'
        instruction_div = soup.find('div', class_='instruction') or \
                          soup.find('div', class_='drug-description') or \
                          soup.find('div', {'itemprop': 'description'})
        if instruction_div:
            # Удаляем лишние элементы (кнопки, скрипты)
            for unwanted in instruction_div.find_all(['script', 'style', 'button', 'form']):
                unwanted.decompose()
            text = instruction_div.get_text(separator='\n', strip=True)
            # Очистка от множественных переносов
            text = '\n'.join(line.strip() for line in text.splitlines() if line.strip())
            return text
        # Если не нашли специальный блок, берём весь текст body (но это много шума)
        body = soup.find('body')
        if body:
            return body.get_text(separator='\n', strip=True)
        return ""

    def get_drug_instruction(self, drug_name: str) -> Dict[str, Any]:
        """
        Основной метод: получает структурированную информацию о препарате.

        Returns:
            Словарь с полями:
            - name: название препарата
            - instruction: полный текст инструкции
            - url: ссылка на источник
            - error: сообщение об ошибке (если есть)
        """
        result = {
            "name": drug_name,
            "instruction": "",
            "url": "",
            "error": None
        }
        drug_url = self._search_drug(drug_name)
        if not drug_url:
            result["error"] = f"Не удалось найти страницу препарата '{drug_name}' на rlsnet.ru"
            return result

        result["url"] = drug_url
        response = self._request_with_retry(drug_url)
        if not response:
            result["error"] = f"Не удалось загрузить страницу {drug_url}"
            return result

        soup = BeautifulSoup(response.text, 'html.parser')
        instruction_text = self._extract_instruction_text(soup)
        if not instruction_text:
            result["error"] = "Не удалось извлечь текст инструкции"
        else:
            result["instruction"] = instruction_text
            self.logger.info(f"Успешно получена инструкция для '{drug_name}' (длина: {len(instruction_text)} символов)")

        return result

    def check_connectivity(self) -> bool:
        """Проверяет доступность сайта."""
        try:
            response = self.session.get(self.base_url, timeout=5)
            return response.status_code == 200
        except:
            return False