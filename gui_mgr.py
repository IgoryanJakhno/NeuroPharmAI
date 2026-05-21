"""
Модуль графического интерфейса пользователя (GUI)

Реализует:
- Окно входа в систему
- Главное окно с вкладками "Поиск" и "Анализ"
- Панель поиска препаратов с фильтрами
- Панель LLM-анализа
- Окно управления пользователями (для администратора)
- Окно настроек системы
- Консоль логов (для старшего пользователя)

Соответствует пунктам ТЗ: 4.2.6, 5.1.5
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import logging
import json
import os
from datetime import datetime
from typing import Optional, Dict, Any

# Импорты модулей ядра
from data_base_mgr import DataBaseManager, AgentCore
from query_parser import QueryParser
from dbms_parser import DBMSParser


class LoginDialog(tk.Toplevel):
    """
    Диалог входа в систему (п. 5.1.5.1).
    """

    def __init__(self, parent, auth_module):
        super().__init__(parent)
        self.auth = auth_module
        self.result = None  # Данные пользователя после успешного входа

        self.title("Нейро-фарм — Вход в систему")
        self.geometry("400x300")
        self.resizable(False, False)
        self.configure(bg="#f0f4f8")

        # Заголовок
        tk.Label(self, text="🔐 Вход в систему", font=("Arial", 16, "bold"),
                 bg="#f0f4f8", fg="#2c3e50").pack(pady=20)

        # Логин
        tk.Label(self, text="Логин:", bg="#f0f4f8", font=("Arial", 10)).pack()
        self.login_entry = tk.Entry(self, width=30, font=("Arial", 11))
        self.login_entry.pack(pady=5)

        # Пароль
        tk.Label(self, text="Пароль:", bg="#f0f4f8", font=("Arial", 10)).pack()
        self.password_entry = tk.Entry(self, width=30, font=("Arial", 11), show="•")
        self.password_entry.pack(pady=5)

        # Кнопка входа
        tk.Button(self, text="Войти", command=self._do_login,
                  bg="#3498db", fg="white", font=("Arial", 11),
                  width=15, height=2).pack(pady=15)

        # Подсказка по паролю
        tk.Button(self, text="Требования к паролю", command=self._show_password_hint,
                  bg="#f0f4f8", fg="#7f8c8d", font=("Arial", 9),
                  bd=0).pack()

        # Сообщение об ошибке
        self.error_label = tk.Label(self, text="", bg="#f0f4f8", fg="red", font=("Arial", 9))
        self.error_label.pack()

    def _do_login(self):
        """Обработка входа."""
        login = self.login_entry.get()
        password = self.password_entry.get()

        success, user_data, message = self.auth.authenticate(login, password)

        if success:
            # Проверяем, не истёк ли пароль
            if "истек" in message.lower() or "истекает" in message.lower():
                messagebox.showwarning("Срок действия пароля", message)
                # Принудительная смена пароля
                new_password = self._prompt_password_change()
                if new_password:
                    success, change_msg = self.auth.change_password(
                        user_data['ID'], password, new_password
                    )
                    messagebox.showinfo("Смена пароля", change_msg)
                    if not success:
                        return  # Не пускаем, если не сменил
                else:
                    return  # Пользователь отказался менять пароль

            self.result = user_data
            self.destroy()
        else:
            self.error_label.config(text=message)
            self.login_entry.delete(0, tk.END)
            self.password_entry.delete(0, tk.END)

    def _prompt_password_change(self) -> Optional[str]:
        """Диалог принудительной смены пароля."""
        dialog = tk.Toplevel(self)
        dialog.title("Смена пароля")
        dialog.geometry("350x250")
        dialog.configure(bg="#f0f4f8")

        tk.Label(dialog, text="🔒 Необходимо сменить пароль",
                 font=("Arial", 12, "bold"), bg="#f0f4f8", fg="#e74c3c").pack(pady=10)

        tk.Label(dialog, text="Старый пароль:", bg="#f0f4f8").pack()
        old_pass = tk.Entry(dialog, show="•", width=30)
        old_pass.pack(pady=5)

        tk.Label(dialog, text="Новый пароль:", bg="#f0f4f8").pack()
        new_pass = tk.Entry(dialog, show="•", width=30)
        new_pass.pack(pady=5)

        tk.Label(dialog, text="Повторите пароль:", bg="#f0f4f8").pack()
        confirm_pass = tk.Entry(dialog, show="•", width=30)
        confirm_pass.pack(pady=5)

        result = [None]  # Список для захвата результата из замыкания

        def do_change():
            if new_pass.get() != confirm_pass.get():
                messagebox.showerror("Ошибка", "Пароли не совпадают")
                return
            if len(new_pass.get()) < 8:
                messagebox.showerror("Ошибка", "Пароль должен быть не менее 8 символов")
                return
            result[0] = new_pass.get()
            dialog.destroy()

        tk.Button(dialog, text="Сменить пароль", command=do_change,
                  bg="#3498db", fg="white", font=("Arial", 11)).pack(pady=15)

        self.wait_window(dialog)
        return result[0]

    def _show_password_hint(self):
        """Показ требований к паролю."""
        hint = (
            "Требования к паролю:\n"
            "• Минимальная длина: 8 символов\n"
            "• Максимальная длина: 20 символов\n"
            "• Запрещены спецсимволы. Пароль должен состоять только из букв латиницы и цифр\n"
        )
        messagebox.showinfo("Требования к паролю", hint)


class SearchPanel(ttk.Frame):
    """
    Панель поиска препаратов (п. 4.2.6).
    """

    def __init__(self, parent, agent: AgentCore, dbms_parser: DBMSParser, user_role: str):
        super().__init__(parent)
        self.agent = agent
        self.dbms_parser = dbms_parser
        self.user_role = user_role

        # Поле ввода запроса
        input_frame = ttk.Frame(self)
        input_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Label(input_frame, text="🔍 Запрос:", font=("Arial", 11)).pack(side=tk.LEFT)
        self.query_entry = ttk.Entry(input_frame, width=60, font=("Arial", 11))
        self.query_entry.pack(side=tk.LEFT, padx=10, fill=tk.X, expand=True)
        self.query_entry.bind("<Return>", lambda e: self._do_search())

        ttk.Button(input_frame, text="Найти", command=self._do_search).pack(side=tk.LEFT, padx=5)

        # Фильтры (опционально)
        filters_frame = ttk.LabelFrame(self, text="Фильтры", padding=10)
        filters_frame.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(filters_frame, text="Производитель:").grid(row=0, column=0, sticky=tk.W, padx=5)
        self.manufacturer_filter = ttk.Entry(filters_frame, width=20)
        self.manufacturer_filter.grid(row=0, column=1, padx=5)

        ttk.Label(filters_frame, text="Страна:").grid(row=0, column=2, sticky=tk.W, padx=5)
        self.country_filter = ttk.Entry(filters_frame, width=20)
        self.country_filter.grid(row=0, column=3, padx=5)

        ttk.Label(filters_frame, text="Форма:").grid(row=0, column=4, sticky=tk.W, padx=5)
        self.form_filter = ttk.Entry(filters_frame, width=15)
        self.form_filter.grid(row=0, column=5, padx=5)

        # Область результатов
        result_frame = ttk.LabelFrame(self, text="Результаты поиска", padding=10)
        result_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.result_text = scrolledtext.ScrolledText(result_frame, wrap=tk.WORD,
                                                     font=("Arial", 10), height=20)
        self.result_text.pack(fill=tk.BOTH, expand=True)

        # Кнопка экспорта (для senior и dev)
        if user_role in ("senior", "dev"):
            ttk.Button(self, text="📄 Экспортировать результаты",
                       command=self._export_results).pack(pady=5)

    def _do_search(self):
        """Выполнение поиска с учётом фильтров."""
        query = self.query_entry.get().strip()
        if not query:
            messagebox.showwarning("Внимание", "Введите поисковый запрос")
            return

        # Парсинг запроса
        parser = QueryParser()
        parsed = parser.parse_query(query)

        logging.debug(f"SearchPanel: Parsed: {parsed}")

        # Добавляем фильтры из полей ввода, если они не были извлечены из запроса
        manufacturer = self.manufacturer_filter.get().strip()
        country = self.country_filter.get().strip()
        form = self.form_filter.get().strip()

        if "error" in parsed and not any([manufacturer, country, form]):
            self.result_text.delete(1.0, tk.END)
            self.result_text.insert(tk.END, f"❌ {parsed['error']}")
            return

        # Если парсер не смог определить intent, но есть фильтры — угадываем intent
        if "error" in parsed:
            if manufacturer:
                parsed = {"intent": "filter_by_manufacturer", "entities": {"manufacturer": manufacturer}}
            elif country:
                parsed = {"intent": "filter_by_country", "entities": {"country": country}}
            elif form:
                parsed = {"intent": "filter_by_form", "entities": {"form": form}}
            else:
                self.result_text.delete(1.0, tk.END)
                self.result_text.insert(tk.END, f"❌ Не удалось распознать запрос")
                return

        # Объединяем сущности из парсера и из фильтров
        entities = parsed.get("entities", {})
        if manufacturer and "manufacturer" not in entities:
            entities["manufacturer"] = manufacturer
        if country and "country" not in entities:
            entities["country"] = country
        if form and "form" not in entities:
            entities["form"] = form

        # Обработка через AgentCore
        try:
            result = self.agent.process_query(parsed["intent"], entities)
        except Exception as e:
            self.result_text.delete(1.0, tk.END)
            self.result_text.insert(tk.END, f"❌ Ошибка обработки запроса: {e}")
            return

        # Форматирование через DBMSParser
        response_text = self.dbms_parser.format_response(result)

        # Вывод
        self.result_text.delete(1.0, tk.END)
        self.result_text.insert(tk.END, response_text)

        logging.debug(f"SearchPanel: Final intent: {parsed['intent']}")
        logging.debug(f"SearchPanel: Final entities: {entities}")

    def _export_results(self):
        """Экспорт результатов в файл."""
        content = self.result_text.get(1.0, tk.END).strip()
        if not content:
            messagebox.showwarning("Внимание", "Нет результатов для экспорта")
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"export_{timestamp}.txt"

        with open(filename, 'w', encoding='utf-8') as f:
            f.write(content)

        messagebox.showinfo("Экспорт", f"Результаты сохранены в файл: {filename}")


class AnalysisPanel(ttk.Frame):
    """
    Панель LLM-анализа (п. 4.2.6).
    """

    def __init__(self, parent, llm_manager=None):
        super().__init__(parent)
        self.llm_manager = llm_manager  # Будет подключён позже на Этапе 6

        # Поле ввода
        input_frame = ttk.Frame(self)
        input_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Label(input_frame, text="🤖 Запрос к LLM:", font=("Arial", 11)).pack(side=tk.LEFT)
        self.llm_query = ttk.Entry(input_frame, width=50, font=("Arial", 11))
        self.llm_query.pack(side=tk.LEFT, padx=10, fill=tk.X, expand=True)

        ttk.Button(input_frame, text="Анализировать", command=self._do_analysis).pack(side=tk.LEFT, padx=5)

        # Область вывода
        result_frame = ttk.LabelFrame(self, text="Результат анализа", padding=10)
        result_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.analysis_text = scrolledtext.ScrolledText(result_frame, wrap=tk.WORD,
                                                       font=("Arial", 10), height=20)
        self.analysis_text.pack(fill=tk.BOTH, expand=True)

        # Заглушка
        self.analysis_text.insert(tk.END, "Модуль LLM будет подключён на Этапе 6 (по плану ТЗ).\n"
                                          "Здесь будет отображаться расширенный анализ запросов.")

    def _do_analysis(self):
        """Выполнение LLM-анализа (заглушка)."""
        messagebox.showinfo("Информация", "LLM-модуль будет подключён позже (Этап 6 по ТЗ).")


class LogConsole(tk.Toplevel):
    """
    Консоль логов (для старшего пользователя, п. 5.1.5.3).
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Консоль логов")
        self.geometry("700x400")

        # Флаг, что окно открыто
        self.is_open = True

        self.log_text = scrolledtext.ScrolledText(self, wrap=tk.WORD,
                                                  font=("Consolas", 9), bg="#1e1e1e", fg="#d4d4d4")
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Кнопки управления
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Button(btn_frame, text="Очистить логи", command=self._clear_logs).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Сохранить логи", command=self._save_logs).pack(side=tk.LEFT, padx=5)

        # Добавляем обработчик логов при открытии окна
        self._setup_log_handler()

        # При закрытии окна удаляем обработчик
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _setup_log_handler(self):
        """Добавление обработчика логов в корневой логгер."""

        class TextHandler(logging.Handler):
            def __init__(self, text_widget):
                super().__init__()
                self.text_widget = text_widget
                self.setLevel(logging.DEBUG)  # Ловить все уровни

            def emit(self, record):
                msg = self.format(record) + "\n"
                # Добавляем цветовое выделение для разных уровней
                tag = None
                if record.levelno == logging.ERROR:
                    tag = "error"
                elif record.levelno == logging.WARNING:
                    tag = "warning"
                elif record.levelno == logging.INFO:
                    tag = "info"
                elif record.levelno == logging.DEBUG:
                    tag = "debug"

                self.text_widget.insert(tk.END, msg)
                if tag:
                    # Добавляем теги для цвета (можно настроить)
                    line_start = self.text_widget.index("end-2l")
                    line_end = self.text_widget.index("end-1c")
                    self.text_widget.tag_add(tag, line_start, line_end)

                self.text_widget.see(tk.END)

        # Настройка цветов
        self.log_text.tag_config("error", foreground="#ff6b6b")
        self.log_text.tag_config("warning", foreground="#ffd93d")
        self.log_text.tag_config("info", foreground="#6bcb77")
        self.log_text.tag_config("debug", foreground="#4d96ff")

        self.log_handler = TextHandler(self.log_text)
        self.log_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s'))
        logging.getLogger().addHandler(self.log_handler)

    def _clear_logs(self):
        """Очистка логов."""
        self.log_text.delete(1.0, tk.END)

    def _save_logs(self):
        """Сохранение логов в файл."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"logs_{timestamp}.txt"
        content = self.log_text.get(1.0, tk.END)
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(content)
        messagebox.showinfo("Сохранение", f"Логи сохранены в {filename}")

    def _on_close(self):
        """Закрытие окна и удаление обработчика."""
        logging.getLogger().removeHandler(self.log_handler)
        self.is_open = False
        self.destroy()

class UserManagementWindow(tk.Toplevel):
    """
    Окно управления пользователями (для администратора, п. 4.2.6).
    """

    def __init__(self, parent, user_manager, admin_id):
        super().__init__(parent)
        self.user_mgr = user_manager
        self.admin_id = admin_id

        self.title("Управление пользователями")
        self.geometry("800x500")

        # Таблица пользователей
        columns = ("ID", "Логин", "Роль", "Срок пароля", "Последний вход")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", height=15)

        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=120)

        self.tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Кнопки управления
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=10, pady=5)

        ttk.Button(btn_frame, text="➕ Добавить", command=self._add_user).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="🔄 Сбросить пароль", command=self._reset_password).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="❌ Удалить", command=self._delete_user).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Обновить список", command=self._refresh).pack(side=tk.LEFT, padx=5)

        self._refresh()

    def _refresh(self):
        """Обновление списка пользователей."""
        for item in self.tree.get_children():
            self.tree.delete(item)

        users = self.user_mgr.get_all_users()
        for user in users:
            self.tree.insert("", tk.END, values=(
                user["ID"],
                user["Username"],
                user["Role"],
                user.get("Password_Expiry", "—"),
                user.get("Last_Login", "—")
            ))

    def _add_user(self):
        """Добавление пользователя (упрощённый диалог)."""
        dialog = tk.Toplevel(self)
        dialog.title("Добавить пользователя")
        dialog.geometry("300x200")

        tk.Label(dialog, text="Логин:").pack()
        login_entry = tk.Entry(dialog)
        login_entry.pack()

        tk.Label(dialog, text="Пароль:").pack()
        pass_entry = tk.Entry(dialog, show="•")
        pass_entry.pack()

        tk.Label(dialog, text="Роль (user/senior/dev):").pack()
        role_entry = tk.Entry(dialog)
        role_entry.pack()

        def do_add():
            success, msg, _ = self.user_mgr.create_user(
                login_entry.get(), pass_entry.get(), role_entry.get(), self.admin_id
            )
            messagebox.showinfo("Результат", msg)
            if success:
                dialog.destroy()
                self._refresh()

        ttk.Button(dialog, text="Создать", command=do_add).pack(pady=10)

    def _reset_password(self):
        """Сброс пароля выбранного пользователя."""
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Внимание", "Выберите пользователя")
            return

        user_id = self.tree.item(selected[0])["values"][0]
        new_pass = f"Reset{datetime.now().strftime('%Y%m%d')}"

        success, msg = self.user_mgr.reset_password(user_id, new_pass, self.admin_id)
        messagebox.showinfo("Результат", f"{msg}\nНовый пароль: {new_pass}")
        self._refresh()

    def _delete_user(self):
        """Удаление выбранного пользователя."""
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Внимание", "Выберите пользователя")
            return

        if not messagebox.askyesno("Подтверждение", "Удалить пользователя?"):
            return

        user_id = self.tree.item(selected[0])["values"][0]
        success, msg = self.user_mgr.delete_user(user_id, self.admin_id)
        messagebox.showinfo("Результат", msg)
        self._refresh()


class SettingsWindow(tk.Toplevel):
    """
    Окно настроек системы (п. 4.2.6).
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Настройки системы")
        self.geometry("500x400")

        notebook = ttk.Notebook(self)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Вкладка FTP
        ftp_frame = ttk.Frame(notebook)
        notebook.add(ftp_frame, text="FTP")

        ttk.Label(ftp_frame, text="Адрес сервера:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        ttk.Entry(ftp_frame, width=40).grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(ftp_frame, text="Порт:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        ttk.Entry(ftp_frame, width=10).grid(row=1, column=1, sticky=tk.W, padx=5, pady=5)

        # Вкладка LLM
        llm_frame = ttk.Frame(notebook)
        notebook.add(llm_frame, text="LLM")

        ttk.Label(llm_frame, text="Макс. длина ответа:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        ttk.Entry(llm_frame, width=20).grid(row=0, column=1, sticky=tk.W, padx=5, pady=5)

        ttk.Label(llm_frame, text="Температура:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        ttk.Entry(llm_frame, width=10).grid(row=1, column=1, sticky=tk.W, padx=5, pady=5)

        # Кнопка сохранения
        ttk.Button(self, text="Сохранить настройки", command=lambda: messagebox.showinfo(
            "Настройки", "Функционал сохранения будет реализован на следующих этапах")
                   ).pack(pady=10)


class MainApplication:
    """
    Главное окно приложения (п. 5.1.5.2).
    """

    def __init__(self, root):
        self.root = root
        self.root.title("Нейро-фарм — Агент-поисковик лекарств")
        self.root.geometry("900x700")

        # Инициализация модулей
        self._init_modules()

        # Данные пользователя
        self.current_user: Optional[Dict[str, Any]] = None

        # Показываем диалог входа
        self._show_login()

    def _init_modules(self):
        """Инициализация всех модулей системы."""
        from auth import DatabaseManager as AuthDB, Authenticator
        from usr_mgr import UserManager

        # Настройка логирования для всего приложения
        logging.basicConfig(level=logging.DEBUG)
        # Убираем вывод в консоль (чтобы не дублировать)
        logging.getLogger().handlers.clear()

        # База данных аутентификации
        self.auth_db = AuthDB("neuro_pharm.db")
        self.auth_db.connect()
        self.auth = Authenticator(self.auth_db)
        self.auth.initialize_database()

        # Менеджер пользователей
        self.user_mgr = UserManager(self.auth_db)

        # База данных лекарств
        self.med_db = DataBaseManager()
        self.med_db_initialized = False

        # Ядро агента
        self.agent = AgentCore(self.med_db)

        # Парсеры
        self.dbms_parser = DBMSParser()

        def setup_logging():
            """Настройка единого логирования для всего приложения."""
            logger = logging.getLogger()
            logger.setLevel(logging.DEBUG)

            # Очищаем старые обработчики, чтобы не было дублирования
            for handler in logger.handlers[:]:
                logger.removeHandler(handler)

            # Формат для консоли GUI
            gui_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s')

            # Обработчик для консоли GUI будет добавлен позже, когда создастся LogConsole
            return logger

    def _init_med_database(self):
        """Инициализация базы лекарств (если ещё не)."""
        if not self.med_db_initialized:
            try:
                self.med_db.initialize_database("egk_extend306")
                self.med_db_initialized = True
            except FileNotFoundError:
                messagebox.showwarning(
                    "Внимание",
                    "База данных лекарств не найдена.\n"
                    "Поместите DBF-файлы в папку egk_extend306."
                )

    def _show_login(self):
        """Показ диалога входа."""
        login_dialog = LoginDialog(self.root, self.auth)
        self.root.wait_window(login_dialog)

        if login_dialog.result:
            self.current_user = login_dialog.result
            self._init_med_database()
            self._build_main_ui()
        else:
            self.root.destroy()

    def _build_main_ui(self):
        """Построение главного интерфейса."""
        # Верхняя панель с информацией о пользователе
        header = ttk.Frame(self.root)
        header.pack(fill=tk.X, padx=10, pady=5)

        user_info = f"👤 {self.current_user['Username']} ({self.current_user['Role']})"
        ttk.Label(header, text=user_info, font=("Arial", 11, "bold")).pack(side=tk.LEFT)

        # Кнопки в зависимости от роли
        if self.current_user["Role"] in ("senior", "dev"):
            ttk.Button(header, text="📋 Консоль логов",
                       command=lambda: LogConsole(self.root)).pack(side=tk.RIGHT, padx=5)

        if self.current_user["Role"] == "dev":
            ttk.Button(header, text="👥 Пользователи",
                       command=lambda: UserManagementWindow(self.root, self.user_mgr, self.current_user["ID"])
                       ).pack(side=tk.RIGHT, padx=5)

        ttk.Button(header, text="⚙️ Настройки",
                   command=lambda: SettingsWindow(self.root)).pack(side=tk.RIGHT, padx=5)

        # Основной контент (вкладки)
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # Вкладка поиска
        search_panel = SearchPanel(notebook, self.agent, self.dbms_parser, self.current_user["Role"])
        notebook.add(search_panel, text="🔍 Поиск")

        # Вкладка анализа
        analysis_panel = AnalysisPanel(notebook)
        notebook.add(analysis_panel, text="🤖 Анализ (LLM)")

        # Строка состояния
        status_bar = ttk.Frame(self.root, relief=tk.SUNKEN)
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)

        ttk.Label(status_bar, text=f"Нейро-фарм v1.0 | База лекарств: {'✅' if self.med_db_initialized else '❌'}"
                  ).pack(side=tk.LEFT, padx=5)
        ttk.Label(status_bar, text=f"Сессия: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
                  ).pack(side=tk.RIGHT, padx=5)

    def run(self):
        """Запуск приложения."""
        self.root.mainloop()


# ============= ТОЧКА ВХОДА =============
if __name__ == "__main__":
    root = tk.Tk()
    app = MainApplication(root)
    app.run()