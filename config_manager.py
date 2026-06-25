"""
Модуль для сохранения и загрузки настроек приложения.
Использует JSON-файл в папке %APPDATA%/NeuroPharm/config.json
"""

import os
import json
import logging

logger = logging.getLogger(__name__)

# Путь к папке с настройками
APP_NAME = "NeuroPharm"
CONFIG_DIR = os.path.join(os.environ.get('APPDATA', '.'), APP_NAME)
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

# Настройки по умолчанию
DEFAULT_CONFIG = {
    "ftp": {
        "host": "ftp.aptekamos.ru",
        "port": 21,
        "username": "anonymous",
        "password": "",
        "remote_file": "egk_extend306.zip",
        "local_dir": "."
    },
    "llm": {
        "max_tokens": 512,
        "temperature": 0.7,
        "timeout": 120,
        "model_name": "llama3.1:8b"
    }
}

def ensure_config_dir():
    """Создаёт директорию для конфигурации, если её нет."""
    if not os.path.exists(CONFIG_DIR):
        os.makedirs(CONFIG_DIR)

def load_config() -> dict:
    """Загружает конфигурацию из файла. Если файла нет — возвращает значения по умолчанию."""
    if not os.path.exists(CONFIG_FILE):
        logger.info("Файл конфигурации не найден, используются значения по умолчанию.")
        return DEFAULT_CONFIG.copy()
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
            # Объединяем с дефолтными настройками (если каких-то ключей нет)
            for section in DEFAULT_CONFIG:
                if section not in config:
                    config[section] = DEFAULT_CONFIG[section]
                else:
                    for key in DEFAULT_CONFIG[section]:
                        if key not in config[section]:
                            config[section][key] = DEFAULT_CONFIG[section][key]
            return config
    except Exception as e:
        logger.error(f"Ошибка загрузки конфигурации: {e}")
        return DEFAULT_CONFIG.copy()

def save_config(config: dict):
    """Сохраняет конфигурацию в файл."""
    ensure_config_dir()
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        logger.info(f"Конфигурация сохранена в {CONFIG_FILE}")
    except Exception as e:
        logger.error(f"Ошибка сохранения конфигурации: {e}")

def get_ftp_config() -> dict:
    """Возвращает FTP-настройки из конфига."""
    config = load_config()
    return config.get("ftp", DEFAULT_CONFIG["ftp"])

def get_llm_config() -> dict:
    """Возвращает LLM-настройки из конфига."""
    config = load_config()
    return config.get("llm", DEFAULT_CONFIG["llm"])