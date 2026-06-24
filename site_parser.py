"""
Модуль SiteParser (Парсер №3) – сбор информации с авторитетного сайта rlsnet.ru.
Улучшенная версия с имитацией браузера и обходом 429.
"""

import requests
import logging
import time
import random
from typing import Optional, Dict, Any
from bs4 import BeautifulSoup
from urllib.parse import urljoin


class SiteParser:
    """
    Парсер для получения подробной информации о лекарственных препаратах с rlsnet.ru.
    """

    def __init__(self, base_url: str = "https://www.rlsnet.ru", timeout: int = 15, retries: int = 2,
                 base_delay: float = 3.0):
        self.base_url = base_url
        self.search_url = urljoin(base_url, "/search.htm")
        self.timeout = timeout
        self.retries = retries
        self.base_delay = base_delay
        self.logger = logging.getLogger("NeuroPharm.SiteParser")
        self.session = requests.Session()

        # Расширенный список User-Agent
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/124.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        ]

        # Базовые заголовки, общие для всех запросов
        self.session.headers.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
        })
        self._set_random_user_agent()

    def _set_random_user_agent(self):
        """Устанавливает случайный User-Agent для текущей сессии."""
        ua = random.choice(self.user_agents)
        self.session.headers.update({"User-Agent": ua})

    def _random_delay(self):
        """Случайная задержка от base_delay-1 до base_delay+3 секунд."""
        delay = self.base_delay + random.uniform(-1, 3)
        if delay < 1:
            delay = 1
        time.sleep(delay)

    def _simulate_user_behavior(self):
        """Имитация поведения пользователя: иногда загружает главную страницу."""
        # Например, один раз из 5 запросов перед поиском переходим на главную
        if random.randint(1, 5) == 1:
            self.logger.debug("Имитация: загрузка главной страницы...")
            try:
                self.session.get(self.base_url, timeout=5)
            except:
                pass
            time.sleep(random.uniform(1, 3))

    def _request_with_retry(self, url: str, params: Optional[Dict] = None) -> Optional[requests.Response]:
        """
        Выполняет HTTP-запрос с повторными попытками.
        При 429 – ждёт и повторяет, но без экспоненциального роста.
        """
        for attempt in range(self.retries):
            # Смена User-Agent при каждой попытке
            self._set_random_user_agent()
            # Случайная задержка перед запросом
            self._random_delay()

            try:
                response = self.session.get(url, params=params, timeout=self.timeout)

                # Если 429 – ждём Retry-After или стандартную задержку
                if response.status_code == 429:
                    self.logger.warning(f"429 на попытке {attempt+1}/{self.retries}")
                    retry_after = response.headers.get("Retry-After")
                    wait_time = int(retry_after) if retry_after and retry_after.isdigit() else 10
                    self.logger.info(f"Ожидание {wait_time} сек...")
                    time.sleep(wait_time)
                    continue

                response.raise_for_status()
                return response
            except requests.exceptions.RequestException as e:
                self.logger.warning(f"Попытка {attempt+1}/{self.retries} не удалась: {e}")
                if attempt == self.retries - 1:
                    self.logger.error(f"Не удалось получить {url}: {e}")
                    return None
        return None

    def _search_drug(self, drug_name: str) -> Optional[str]:
        """Поиск страницы препарата по полному названию с имитацией поведения."""
        # Имитация пользовательского поведения
        self._simulate_user_behavior()

        self.logger.info(f"Поиск препарата '{drug_name}'")
        params = {"query": drug_name}
        response = self._request_with_retry(self.search_url, params)
        if not response:
            return None

        # Проверка, что вернулась не страница с ошибкой/капчей
        if "captcha" in response.text.lower() or "доступ запрещен" in response.text.lower():
            self.logger.error("Вероятно, сайт вернул капчу или блокировку")
            return None

        soup = BeautifulSoup(response.text, 'html.parser')
        full_url = None
        for link in soup.find_all('a', href=True):
            href = link['href']
            if '/drugs/' in href and 'инструкция' in link.get_text().lower():
                full_url = urljoin(self.base_url, href)
                self.logger.info(f"Найдена страница инструкции: {full_url}")
                return full_url
            if '/drugs/' in href and not full_url:
                full_url = urljoin(self.base_url, href)
        if full_url:
            self.logger.info(f"Найдена страница препарата (запасной вариант): {full_url}")
        else:
            self.logger.warning(f"Не найдена страница для '{drug_name}'")
        return full_url

    def _extract_instruction_text(self, soup: BeautifulSoup) -> str:
        """Извлекает текст инструкции из HTML."""
        instruction_div = soup.find('div', class_='instruction') or \
                          soup.find('div', class_='drug-description') or \
                          soup.find('div', {'itemprop': 'description'}) or \
                          soup.find('div', class_='drug-info')
        if instruction_div:
            # Удаляем ненужные теги
            for unwanted in instruction_div.find_all(['script', 'style', 'button', 'form', 'nav', 'footer']):
                unwanted.decompose()
            text = instruction_div.get_text(separator='\n', strip=True)
            # Чистка от лишних пустых строк
            return '\n'.join(line.strip() for line in text.splitlines() if line.strip())
        body = soup.find('body')
        if body:
            return body.get_text(separator='\n', strip=True)[:5000]
        return ""

    def get_drug_instruction(self, drug_name: str) -> Dict[str, Any]:
        """Основной метод: получает инструкцию."""
        result = {"name": drug_name, "instruction": "", "url": "", "error": None}
        drug_url = self._search_drug(drug_name)
        if not drug_url:
            result["error"] = f"Страница препарата '{drug_name}' не найдена"
            return result

        result["url"] = drug_url
        # Имитация перед загрузкой инструкции
        time.sleep(random.uniform(1, 2))
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
            self.logger.info(f"Инструкция получена (длина {len(instruction_text)} символов)")
        return result

    def check_connectivity(self) -> bool:
        """Проверка доступности сайта (с задержкой)."""
        time.sleep(random.uniform(1, 3))
        try:
            resp = self.session.get(self.base_url, timeout=5)
            return resp.status_code == 200
        except:
            return False