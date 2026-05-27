"""
Модуль FTP-агента для обновления базы данных лекарственных препаратов.

Соответствует ТЗ п. 4.2.3:
- Адрес FTP-сервера: ftp.aptekamos.ru
- Порт: 21 (стандартный)
- Скачивание файла egk_extend306.zip
- Распаковка ZIP-архива
- Удаление архива после распаковки
- Логирование всех операций
"""

import os
import zipfile
import logging
import shutil
from ftplib import FTP, error_perm, error_temp, error_reply
from typing import Optional, Tuple
from datetime import datetime
import tempfile


class FTPAgent:
    """
    FTP-агент для работы с сервером РОСЛЕКа.

    Атрибуты:
        host: Адрес FTP-сервера
        port: Порт FTP-сервера
        username: Имя пользователя (анонимный доступ)
        password: Пароль
        remote_file: Имя файла на сервере
        local_dir: Локальная директория для сохранения
        temp_dir: Временная директория для скачивания
        logger: Логгер для записи операций
    """

    def __init__(
            self,
            host: str = "ftp.aptekamos.ru",
            port: int = 21,
            username: str = "anonymous",
            password: str = "",
            remote_file: str = "egk_extend306.zip",
            local_dir: str = "."
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.remote_file = remote_file
        self.local_dir = local_dir
        self.temp_dir = None
        self.ftp: Optional[FTP] = None
        self.logger = logging.getLogger("NeuroPharm.FTP")

        # Расширенный путь к локальной папке (куда будет распаковываться)
        self.extract_dir = os.path.join(local_dir, "egk_extend306")

        # Настройка логирования, если ещё не настроено
        if not logging.getLogger().handlers:
            logging.basicConfig(level=logging.INFO)

    def _connect(self) -> bool:
        """
        Установление соединения с FTP-сервером.

        Returns:
            True при успешном подключении, иначе False
        """
        try:
            self.logger.info(f"Подключение к FTP-серверу {self.host}:{self.port}")
            self.ftp = FTP()
            self.ftp.connect(self.host, self.port, timeout=30)
            self.ftp.login(self.username, self.password)
            self.ftp.voidcmd("TYPE I")  # Бинарный режим для ZIP-файлов
            self.logger.info(f"Успешное подключение к {self.host}")
            return True
        except error_perm as e:
            self.logger.error(f"Ошибка авторизации на FTP-сервере: {e}")
            return False
        except (error_temp, error_reply) as e:
            self.logger.error(f"Временная ошибка FTP: {e}")
            return False
        except Exception as e:
            self.logger.error(f"Не удалось подключиться к FTP-серверу: {e}")
            return False

    def _disconnect(self):
        """Закрытие соединения с FTP-сервером."""
        if self.ftp:
            try:
                self.ftp.quit()
                self.logger.info("Соединение с FTP-сервером закрыто")
            except Exception as e:
                self.logger.warning(f"Ошибка при закрытии соединения: {e}")
            finally:
                self.ftp = None

    def _get_remote_file_size(self) -> Optional[int]:
        """
        Получение размера файла на сервере.

        Returns:
            Размер файла в байтах или None при ошибке
        """
        if not self.ftp:
            return None
        try:
            size = self.ftp.size(self.remote_file)
            self.logger.debug(f"Размер файла на сервере: {size} байт")
            return size
        except Exception as e:
            self.logger.warning(f"Не удалось получить размер файла: {e}")
            return None

    def _check_local_file_exists(self) -> Tuple[bool, Optional[int]]:
        """
        Проверка существования локального ZIP-файла и его размера.

        Returns:
            (существует, размер_в_байтах)
        """
        local_zip_path = os.path.join(self.local_dir, self.remote_file)
        if os.path.exists(local_zip_path):
            size = os.path.getsize(local_zip_path)
            return True, size
        return False, None

    def _check_local_extracted(self) -> bool:
        """
        Проверка, распакована ли уже база данных локально.

        Returns:
            True, если папка с распакованными DBF-файлами существует
        """
        return os.path.exists(self.extract_dir) and len(os.listdir(self.extract_dir)) > 0

    def check_for_updates(self) -> Tuple[bool, str]:
        """
        Проверка, доступно ли обновление на сервере.

        Returns:
            (есть_обновление, сообщение)
        """
        try:
            if not self._connect():
                return False, "Не удалось подключиться к FTP-серверу"

            # Получаем дату изменения файла на сервере
            try:
                self.ftp.voidcmd(f"MDTM {self.remote_file}")
                # MDTM возвращает код 213, но в Python FTP не парсит ответ
                # Альтернатива: используем MLSD, если поддерживается
                self.logger.info("FTP-сервер поддерживает MDTM")
            except Exception:
                self.logger.warning("Не удалось получить дату изменения файла")

            remote_size = self._get_remote_file_size()
            local_exists, local_size = self._check_local_file_exists()

            self._disconnect()

            if not remote_size:
                return True, "Не удалось определить размер файла на сервере. Рекомендуется обновить."

            if not local_exists:
                return True, "Локальная база данных не найдена. Требуется загрузка."

            if local_size != remote_size:
                return True, f"Размер файла отличается (сервер: {remote_size}, локальный: {local_size})"

            return False, "База данных актуальна"

        except Exception as e:
            self.logger.error(f"Ошибка при проверке обновлений: {e}")
            return True, f"Ошибка проверки: {e}"

    def download_file(self) -> Tuple[bool, str]:
        """
        Скачивание ZIP-файла с FTP-сервера.

        Returns:
            (успех, сообщение)
        """
        try:
            if not self._connect():
                return False, "Не удалось подключиться к FTP-серверу"

            # Создаём временную директорию для скачивания
            self.temp_dir = tempfile.mkdtemp(prefix="neuropharm_ftp_")
            local_zip_path = os.path.join(self.temp_dir, self.remote_file)

            self.logger.info(f"Начало скачивания {self.remote_file} с {self.host}")

            # Открываем файл для записи в бинарном режиме
            with open(local_zip_path, 'wb') as local_file:

                def callback(data):
                    local_file.write(data)

                # Скачиваем файл
                self.ftp.retrbinary(f"RETR {self.remote_file}", callback)

            file_size = os.path.getsize(local_zip_path)
            self.logger.info(f"Файл успешно скачан: {file_size} байт")

            self._disconnect()

            # Перемещаем файл в корневую директорию
            final_zip_path = os.path.join(self.local_dir, self.remote_file)
            shutil.move(local_zip_path, final_zip_path)

            # Удаляем временную директорию
            shutil.rmtree(self.temp_dir)
            self.temp_dir = None

            self.logger.info(f"ZIP-файл сохранён в {final_zip_path}")
            return True, f"Файл успешно скачан ({file_size // 1024} КБ)"

        except Exception as e:
            self.logger.error(f"Ошибка при скачивании файла: {e}")
            # Очистка временной директории при ошибке
            if self.temp_dir and os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir, ignore_errors=True)
            return False, f"Ошибка скачивания: {e}"

    def extract_archive(self) -> Tuple[bool, str]:
        """
        Распаковка ZIP-архива в корневую папку.

        Returns:
            (успех, сообщение)
        """
        zip_path = os.path.join(self.local_dir, self.remote_file)

        if not os.path.exists(zip_path):
            return False, f"ZIP-файл не найден: {zip_path}"

        try:
            self.logger.info(f"Начало распаковки {zip_path}")

            # Создаём резервную копию, если папка существует
            if os.path.exists(self.extract_dir):
                backup_dir = f"{self.extract_dir}_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                shutil.move(self.extract_dir, backup_dir)
                self.logger.info(f"Создана резервная копия: {backup_dir}")

            # Создаём целевую директорию
            os.makedirs(self.extract_dir, exist_ok=True)

            # Распаковываем архив
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                # Проверяем, есть ли в архиве папка или файлы в корне
                file_list = zip_ref.namelist()

                # Если в архиве есть одна папка, распаковываем её содержимое
                if len(file_list) == 1 and file_list[0].endswith('/'):
                    # В архиве только одна папка
                    for file in zip_ref.namelist():
                        if file != file_list[0]:  # не сама папка
                            zip_ref.extract(file, self.local_dir)
                    # Перемещаем содержимое
                    extracted_folder = os.path.join(self.local_dir, file_list[0])
                    if os.path.exists(extracted_folder):
                        for item in os.listdir(extracted_folder):
                            shutil.move(
                                os.path.join(extracted_folder, item),
                                os.path.join(self.extract_dir, item)
                            )
                        shutil.rmtree(extracted_folder)
                else:
                    # Распаковываем всё в целевую директорию
                    zip_ref.extractall(self.extract_dir)

            self.logger.info(f"Архив успешно распакован в {self.extract_dir}")

            # Считаем количество распакованных DBF-файлов
            dbf_count = len([f for f in os.listdir(self.extract_dir) if f.endswith('.dbf')])

            return True, f"Архив распакован. Найдено {dbf_count} DBF-файлов."

        except zipfile.BadZipFile:
            self.logger.error("Ошибка: файл не является ZIP-архивом")
            return False, "Файл повреждён или не является ZIP-архивом"
        except Exception as e:
            self.logger.error(f"Ошибка при распаковке: {e}")
            return False, f"Ошибка распаковки: {e}"

    def delete_archive(self) -> Tuple[bool, str]:
        """
        Удаление ZIP-архива после успешной распаковки.

        Returns:
            (успех, сообщение)
        """
        zip_path = os.path.join(self.local_dir, self.remote_file)

        if not os.path.exists(zip_path):
            return True, "ZIP-файл уже удалён или не существует"

        try:
            os.remove(zip_path)
            self.logger.info(f"ZIP-архив удалён: {zip_path}")
            return True, "ZIP-архив удалён для экономии места"
        except Exception as e:
            self.logger.error(f"Ошибка при удалении архива: {e}")
            return False, f"Не удалось удалить архив: {e}"

    def update_database(self) -> Tuple[bool, str]:
        """
        Полный цикл обновления базы данных:
        1. Проверка наличия обновлений
        2. Скачивание
        3. Распаковка
        4. Удаление архива

        Returns:
            (успех, сообщение)
        """
        self.logger.info("=" * 50)
        self.logger.info("Начало обновления базы данных")
        self.logger.info("=" * 50)

        # Шаг 1: Проверяем, не распакована ли уже база
        if self._check_local_extracted():
            self.logger.info("Локальная база данных уже существует")

            # Проверяем обновления на сервере
            has_update, check_msg = self.check_for_updates()
            if not has_update:
                return True, check_msg
            self.logger.info(check_msg)

        # Шаг 2: Скачивание
        success, msg = self.download_file()
        if not success:
            return False, f"Ошибка скачивания: {msg}"
        self.logger.info(msg)

        # Шаг 3: Распаковка
        success, msg = self.extract_archive()
        if not success:
            return False, f"Ошибка распаковки: {msg}"
        self.logger.info(msg)

        # Шаг 4: Удаление архива
        success, msg = self.delete_archive()
        self.logger.info(msg)

        self.logger.info("Обновление базы данных завершено успешно!")
        return True, "База данных успешно обновлена"

    def update_settings(self, host: str = None, port: int = None,
                        username: str = None, password: str = None,
                        remote_file: str = None, local_dir: str = None):
        """
        Обновление настроек FTP-соединения.

        Args:
            host: Адрес FTP-сервера
            port: Порт
            username: Имя пользователя
            password: Пароль
            remote_file: Имя файла на сервере
            local_dir: Локальная директория
        """
        if host:
            self.host = host
        if port:
            self.port = port
        if username is not None:
            self.username = username
        if password is not None:
            self.password = password
        if remote_file:
            self.remote_file = remote_file
        if local_dir:
            self.local_dir = local_dir
            self.extract_dir = os.path.join(local_dir, "egk_extend306")

        self.logger.info(f"Настройки FTP обновлены: {self.host}:{self.port}")


# ============= ТЕСТОВЫЙ БЛОК =============
# if __name__ == "__main__":
#     # Настройка логирования
#     logging.basicConfig(
#         level=logging.DEBUG,
#         format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
#     )
#
#     print("=" * 60)
#     print("ТЕСТИРОВАНИЕ FTP-АГЕНТА")
#     print("=" * 60)
#
#     # Создаём агента с настройками по умолчанию (РОСЛЕК)
#     agent = FTPAgent(
#         host="ftp.aptekamos.ru",
#         port=21,
#         username="anonymous",
#         password="",
#         remote_file="egk_extend306.zip",
#         local_dir="."
#     )
#
#     # Проверяем наличие обновлений
#     print("\n1. Проверка обновлений...")
#     has_update, msg = agent.check_for_updates()
#     print(f"   Результат: {msg}")
#
#     # Полное обновление
#     print("\n2. Запуск полного обновления...")
#     success, msg = agent.update_database()
#     print(f"   Результат: {'✅' if success else '❌'} {msg}")