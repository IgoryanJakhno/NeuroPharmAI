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
from llm_mgr import LLMManager
from ftp_agent import FTPAgent
from site_parser import SiteParser
from config_manager import load_config, save_config

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

        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")

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

    def _show_formatted_text(self, text: str, tag: str = None):
        """Отображает текст с форматированием (жирный, заголовки, списки)."""
        self.result_text.delete(1.0, tk.END)

        if tag:
            self.result_text.insert(tk.END, text, tag)
            return

        # Настройка тегов
        self.result_text.tag_configure("bold", font=("Arial", 10, "bold"))
        self.result_text.tag_configure("header", font=("Arial", 11, "bold"), foreground="#2c3e50")
        self.result_text.tag_configure("subheader", font=("Arial", 10, "bold"), foreground="#34495e")
        self.result_text.tag_configure("list_item", font=("Arial", 10), lmargin1=20, lmargin2=30)
        self.result_text.tag_configure("error", font=("Arial", 10), foreground="red")
        self.result_text.tag_configure("warning", font=("Arial", 10), foreground="#e67e22")
        self.result_text.tag_configure("disclaimer", font=("Arial", 9, "italic"), foreground="#7f8c8d")

        for line in text.split('\n'):
            stripped = line.strip()

            if stripped.startswith('⚠️ Информация носит справочный'):
                self.result_text.insert(tk.END, line + '\n', "disclaimer")
            elif stripped.startswith('📋') or stripped.startswith('💊') or stripped.startswith(
                    '🔍') or stripped.startswith('📊') or stripped.startswith('⚠️ Побочные'):
                self.result_text.insert(tk.END, line + '\n', "header")
            elif stripped.startswith('🔹') or stripped.startswith('🔸'):
                self.result_text.insert(tk.END, line + '\n', "subheader")
            elif stripped and (stripped[0].isdigit() or stripped.startswith('•') or stripped.startswith('  ')):
                self.result_text.insert(tk.END, line + '\n', "list_item")
            elif stripped.startswith('⚠️'):
                self.result_text.insert(tk.END, line + '\n', "warning")
            elif '**' in stripped:
                clean = stripped.replace('**', '')
                self.result_text.insert(tk.END, clean + '\n', "bold")
            else:
                self.result_text.insert(tk.END, line + '\n')

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
            self._show_formatted_text(f"❌ {parsed['error']}", "error")
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
                self._show_formatted_text("❌ Не удалось распознать запрос", "error")
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
            self._show_formatted_text(f"❌ Ошибка обработки запроса: {e}", "error")
            return

        # Форматирование через DBMSParser
        response_text = self.dbms_parser.format_response(result)

        # Вывод
        self._show_formatted_text(response_text)

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

    def __init__(self, parent, llm_manager=None, dbms_parser=None, current_user=None):
        super().__init__(parent)
        self.llm_manager = llm_manager
        self.dbms_parser = dbms_parser
        self.current_user = current_user  # Для проверки роли (senior/dev)

        # Поле ввода
        input_frame = ttk.Frame(self)
        input_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Label(input_frame, text="🤖 Запрос к LLM:", font=("Arial", 11)).pack(side=tk.LEFT)
        self.llm_query = ttk.Entry(input_frame, width=50, font=("Arial", 11))
        self.llm_query.pack(side=tk.LEFT, padx=10, fill=tk.X, expand=True)
        self.llm_query.bind("<Return>", lambda e: self._do_analysis())

        ttk.Button(input_frame, text="Анализировать", command=self._do_analysis).pack(side=tk.LEFT, padx=5)

        # Область вывода
        result_frame = ttk.LabelFrame(self, text="Результат анализа", padding=10)
        result_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.analysis_text = scrolledtext.ScrolledText(result_frame, wrap=tk.WORD,
                                                       font=("Arial", 10), height=20)
        self.analysis_text.pack(fill=tk.BOTH, expand=True)

        # Кнопка экспорта (для senior и dev)
        if self.current_user and self.current_user.get("Role") in ("senior", "dev"):
            ttk.Button(self, text="📄 Экспортировать ответ",
                       command=self._export_response).pack(pady=5)

        if self.llm_manager:
            status = "✅" if self.llm_manager.check_availability() else "❌"
            self.analysis_text.insert(tk.END, f"LLM подключена: {status}\nГотова к анализу запросов.")
        else:
            self.analysis_text.insert(tk.END, "LLM-модуль не подключён.")

    def _show_formatted_text(self, text: str, tag: str = None):
        """Отображает текст с форматированием."""
        self.analysis_text.delete(1.0, tk.END)

        if tag:
            self.analysis_text.insert(tk.END, text, tag)
            return

        self.analysis_text.tag_configure("bold", font=("Arial", 10, "bold"))
        self.analysis_text.tag_configure("header", font=("Arial", 11, "bold"), foreground="#2c3e50")
        self.analysis_text.tag_configure("list_item", font=("Arial", 10), lmargin1=20, lmargin2=30)
        self.analysis_text.tag_configure("error", font=("Arial", 10), foreground="red")
        self.analysis_text.tag_configure("disclaimer", font=("Arial", 9, "italic"), foreground="#7f8c8d")

        for line in text.split('\n'):
            stripped = line.strip()

            if stripped.startswith('⚠️ Информация носит справочный'):
                self.analysis_text.insert(tk.END, line + '\n', "disclaimer")
            elif '**' in stripped and stripped.startswith('**'):
                clean = stripped.replace('**', '')
                self.analysis_text.insert(tk.END, clean + '\n', "header")
            elif stripped.startswith('* ') or stripped.startswith('  '):
                self.analysis_text.insert(tk.END, line + '\n', "list_item")
            elif '**' in stripped:
                clean = stripped.replace('**', '')
                self.analysis_text.insert(tk.END, clean + '\n', "bold")
            else:
                self.analysis_text.insert(tk.END, line + '\n')

    def _do_analysis(self):
        """Выполнение LLM-анализа с подробным логированием."""
        if not self.llm_manager:
            messagebox.showinfo("Информация", "LLM-модуль не подключён.")
            return

        query = self.llm_query.get().strip()
        if not query:
            messagebox.showwarning("Внимание", "Введите запрос для анализа")
            return

        # --- Логирование: Шаг 1 — Парсинг запроса ---
        from query_parser import QueryParser
        parser = QueryParser()
        parsed = parser.parse_query(query)

        logging.getLogger("NeuroPharm.LLM").info(f"[LLM-анализ] Исходный запрос: '{query}'")
        logging.getLogger("NeuroPharm.LLM").info(f"[LLM-анализ] Intent: {parsed.get('intent', 'не определён')}")
        logging.getLogger("NeuroPharm.LLM").info(f"[LLM-анализ] Сущности: {parsed.get('entities', {})}")

        # --- Если есть DBMSParser и AgentCore, делаем полный цикл ---
        if self.dbms_parser and hasattr(self, 'agent'):
            try:
                # Получаем результат от AgentCore
                result = self.agent.process_query(parsed.get("intent", ""), parsed.get("entities", {}))

                # Формируем промпт для LLM через DBMSParser
                llm_prompt = self.dbms_parser.format_for_llm(result)

                # Логирование: Шаг 2 — Сформированный ввод нейросети
                logging.getLogger("NeuroPharm.LLM").info(f"[LLM-анализ] Сформированный промпт:\n{llm_prompt}")

                # Отправляем в LLM
                response = self.llm_manager.generate_response(llm_prompt)
            except Exception as e:
                logging.getLogger("NeuroPharm.LLM").error(f"[LLM-анализ] Ошибка полного цикла: {e}")
                response = self.llm_manager.generate_response(query)
        else:
            # Простой режим: отправляем запрос напрямую
            logging.getLogger("NeuroPharm.LLM").info(f"[LLM-анализ] Прямой запрос к LLM (без AgentCore)")
            response = self.llm_manager.generate_response(query)

        # --- Логирование: Шаг 3 — Ответ модели ---
        if response:
            logging.getLogger("NeuroPharm.LLM").info(f"[LLM-анализ] Ответ получен ({len(response)} символов)")
            logging.getLogger("NeuroPharm.LLM").debug(f"[LLM-анализ] Текст ответа:\n{response}")
        else:
            logging.getLogger("NeuroPharm.LLM").error("[LLM-анализ] Ответ не получен")

        # Вывод в интерфейс
        if response:
            self._show_formatted_text(response)
        else:
            self._show_formatted_text("❌ Не удалось получить ответ от LLM.\n"
                                      "Проверьте, что Ollama запущена (ollama serve).", "error")

    def _export_response(self):
        """Экспорт ответа модели в файл."""
        content = self.analysis_text.get(1.0, tk.END).strip()
        if not content or "LLM подключена" in content:
            messagebox.showwarning("Внимание", "Нет результата анализа для экспорта")
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"llm_export_{timestamp}.txt"

        with open(filename, 'w', encoding='utf-8') as f:
            f.write(content)

        messagebox.showinfo("Экспорт", f"Результат анализа сохранён в файл: {filename}")
        logging.getLogger("NeuroPharm.LLM").info(f"[LLM-анализ] Ответ экспортирован в {filename}")

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

    def __init__(self, parent, llm_manager=None, ftp_agent=None):
        super().__init__(parent)
        self.llm_manager = llm_manager
        self.ftp_agent = ftp_agent
        self.title("Настройки системы")
        self.geometry("500x450")
        self.resizable(False, False)

        notebook = ttk.Notebook(self)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # --- ЗАГРУЗКА ТЕКУЩИХ НАСТРОЕК ДЛЯ ПОЛЕЙ ---
        # LLM: если менеджер есть – берём из него, иначе из конфига
        if llm_manager:
            max_tokens = llm_manager.max_tokens
            temperature = llm_manager.temperature
            timeout = llm_manager.timeout
            model_name = llm_manager.model_name
        else:
            config = load_config()
            llm_cfg = config.get("llm", {})
            max_tokens = llm_cfg.get("max_tokens", 512)
            temperature = llm_cfg.get("temperature", 0.7)
            timeout = llm_cfg.get("timeout", 120)
            model_name = llm_cfg.get("model_name", "llama3.1:8b")

        # FTP: если агент есть – берём из него, иначе из конфига
        if ftp_agent:
            ftp_host = ftp_agent.host
            ftp_port = ftp_agent.port
            ftp_user = ftp_agent.username
            ftp_pass = ftp_agent.password
        else:
            config = load_config()
            ftp_cfg = config.get("ftp", {})
            ftp_host = ftp_cfg.get("host", "ftp.aptekamos.ru")
            ftp_port = ftp_cfg.get("port", 21)
            ftp_user = ftp_cfg.get("username", "anonymous")
            ftp_pass = ftp_cfg.get("password", "")

        # ===== Вкладка LLM =====
        llm_frame = ttk.Frame(notebook)
        notebook.add(llm_frame, text="🤖 LLM")

        ttk.Label(llm_frame, text="Максимальная длина ответа (токенов):", font=("Arial", 10)).grid(
            row=0, column=0, sticky=tk.W, padx=10, pady=(15, 5))
        self.max_tokens_var = tk.StringVar(value=str(max_tokens))
        ttk.Entry(llm_frame, textvariable=self.max_tokens_var, width=15, font=("Arial", 10)).grid(
            row=0, column=1, sticky=tk.W, padx=10, pady=(15, 5))
        ttk.Label(llm_frame, text="(50–4096)", foreground="gray").grid(
            row=0, column=2, sticky=tk.W, padx=5, pady=(15, 5))

        ttk.Label(llm_frame, text="Температура генерации:", font=("Arial", 10)).grid(
            row=1, column=0, sticky=tk.W, padx=10, pady=5)
        self.temperature_var = tk.StringVar(value=str(temperature))
        ttk.Entry(llm_frame, textvariable=self.temperature_var, width=15, font=("Arial", 10)).grid(
            row=1, column=1, sticky=tk.W, padx=10, pady=5)
        ttk.Label(llm_frame, text="(0.0–2.0)", foreground="gray").grid(
            row=1, column=2, sticky=tk.W, padx=5, pady=5)

        ttk.Label(llm_frame, text="Таймаут запроса (сек):", font=("Arial", 10)).grid(
            row=2, column=0, sticky=tk.W, padx=10, pady=5)
        self.timeout_var = tk.StringVar(value=str(timeout))
        ttk.Entry(llm_frame, textvariable=self.timeout_var, width=15, font=("Arial", 10)).grid(
            row=2, column=1, sticky=tk.W, padx=10, pady=5)
        ttk.Label(llm_frame, text="(30–600)", foreground="gray").grid(
            row=2, column=2, sticky=tk.W, padx=5, pady=5)

        ttk.Label(llm_frame, text="Модель:", font=("Arial", 10)).grid(
            row=3, column=0, sticky=tk.W, padx=10, pady=5)
        self.model_var = tk.StringVar(value=model_name)
        ttk.Entry(llm_frame, textvariable=self.model_var, width=25, font=("Arial", 10)).grid(
            row=3, column=1, sticky=tk.W, padx=10, pady=5)

        # Кнопка проверки соединения
        ttk.Button(llm_frame, text="Проверить соединение", command=self._check_llm).grid(
            row=4, column=0, columnspan=3, pady=15)
        self.llm_status_label = ttk.Label(llm_frame, text="", font=("Arial", 9))
        self.llm_status_label.grid(row=5, column=0, columnspan=3)

        # ===== Вкладка FTP =====
        ftp_frame = ttk.Frame(notebook)
        notebook.add(ftp_frame, text="📁 FTP")

        ttk.Label(ftp_frame, text="Настройки FTP-сервера", font=("Arial", 11, "bold")).grid(
            row=0, column=0, columnspan=2, pady=10, padx=10, sticky=tk.W)

        ttk.Label(ftp_frame, text="Адрес сервера:").grid(row=1, column=0, sticky=tk.W, padx=10, pady=5)
        self.ftp_host_var = tk.StringVar(value=ftp_host)
        ttk.Entry(ftp_frame, textvariable=self.ftp_host_var, width=30).grid(row=1, column=1, padx=10, pady=5)

        ttk.Label(ftp_frame, text="Порт:").grid(row=2, column=0, sticky=tk.W, padx=10, pady=5)
        self.ftp_port_var = tk.StringVar(value=str(ftp_port))
        ttk.Entry(ftp_frame, textvariable=self.ftp_port_var, width=10).grid(row=2, column=1, sticky=tk.W, padx=10,
                                                                            pady=5)

        ttk.Label(ftp_frame, text="Пользователь:").grid(row=3, column=0, sticky=tk.W, padx=10, pady=5)
        self.ftp_user_var = tk.StringVar(value=ftp_user)
        ttk.Entry(ftp_frame, textvariable=self.ftp_user_var, width=30).grid(row=3, column=1, padx=10, pady=5)

        ttk.Label(ftp_frame, text="Пароль:").grid(row=4, column=0, sticky=tk.W, padx=10, pady=5)
        self.ftp_pass_var = tk.StringVar(value=ftp_pass)
        ttk.Entry(ftp_frame, textvariable=self.ftp_pass_var, width=30, show="•").grid(row=4, column=1, padx=10,
                                                                                      pady=5)

        # Кнопка проверки соединения
        ttk.Button(ftp_frame, text="Проверить соединение", command=self._check_ftp).grid(
            row=5, column=0, columnspan=2, pady=15)
        self.ftp_status_label = ttk.Label(ftp_frame, text="", font=("Arial", 9))
        self.ftp_status_label.grid(row=6, column=0, columnspan=2)

        # ===== Кнопки =====
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Button(btn_frame, text="💾 Сохранить настройки", command=self._save_settings).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="🔄 По умолчанию", command=self._reset_defaults).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Закрыть", command=self.destroy).pack(side=tk.RIGHT, padx=5)

    def _check_ftp(self):
        """Проверка соединения с FTP-сервером."""
        if not self.ftp_agent:
            self.ftp_status_label.config(text="⚠️ FTP-агент не инициализирован", foreground="orange")
            return

        # Применяем текущие настройки из полей ввода
        self.ftp_agent.update_settings(
            host=self.ftp_host_var.get().strip(),
            port=int(self.ftp_port_var.get()),
            username=self.ftp_user_var.get().strip(),
            password=self.ftp_pass_var.get(),
            remote_file="egk_extend306.zip",
            local_dir="."
        )

        # Выполняем проверку
        has_update, msg = self.ftp_agent.check_for_updates()

        if has_update:
            # Сервер доступен, но файл отличается или не найден
            if "подключиться" in msg or "FTP" in msg:
                self.ftp_status_label.config(text=f"❌ {msg}", foreground="red")
            else:
                self.ftp_status_label.config(text=f"🔄 Доступен: {msg}", foreground="orange")
        else:
            self.ftp_status_label.config(text=f"✅ {msg}", foreground="green")

    def _check_llm(self):
        """Проверка соединения с Ollama."""
        if self.llm_manager:
            if self.llm_manager.check_availability():
                self.llm_status_label.config(text="✅ Соединение установлено", foreground="green")
            else:
                self.llm_status_label.config(text="❌ Сервер недоступен", foreground="red")
        else:
            self.llm_status_label.config(text="⚠️ LLM-менеджер не инициализирован", foreground="orange")

    def _save_settings(self):
        try:
            if self.llm_manager:
                self.llm_manager.max_tokens = int(self.max_tokens_var.get())
                self.llm_manager.temperature = float(self.temperature_var.get())
                self.llm_manager.timeout = int(self.timeout_var.get())
                new_model = self.model_var.get().strip()
                if new_model:
                    self.llm_manager.model_name = new_model

            if self.ftp_agent:
                self.ftp_agent.update_settings(
                    host=self.ftp_host_var.get().strip(),
                    port=int(self.ftp_port_var.get()),
                    username=self.ftp_user_var.get().strip(),
                    password=self.ftp_pass_var.get(),
                    remote_file="egk_extend306.zip",
                    local_dir="."
                )

            # --- СОХРАНЕНИЕ В ФАЙЛ (добавить этот блок) ---
            config = {
                "ftp": {
                    "host": self.ftp_host_var.get().strip(),
                    "port": int(self.ftp_port_var.get()),
                    "username": self.ftp_user_var.get().strip(),
                    "password": self.ftp_pass_var.get(),
                    "remote_file": "egk_extend306.zip",
                    "local_dir": "."
                },
                "llm": {
                    "max_tokens": int(self.max_tokens_var.get()),
                    "temperature": float(self.temperature_var.get()),
                    "timeout": int(self.timeout_var.get()),
                    "model_name": self.model_var.get().strip()
                }
            }
            save_config(config)

            logging.getLogger("NeuroPharm.GUI").info(f"Настройки сохранены")
            messagebox.showinfo("Настройки", "Настройки успешно сохранены.")
        except ValueError as e:
            messagebox.showerror("Ошибка", f"Некорректное значение: {e}")

    def _reset_defaults(self):
        """Сброс настроек на значения по умолчанию."""
        self.max_tokens_var.set("512")
        self.temperature_var.set("0.7")
        self.timeout_var.set("120")
        self.model_var.set("llama3.1:8b")
        self.ftp_host_var.set("ftp.aptekamos.ru")
        self.ftp_port_var.set("21")
        self.ftp_user_var.set("anonymous")
        self.ftp_pass_var.set("")
        messagebox.showinfo("Настройки", "Настройки сброшены на значения по умолчанию.")

class MainApplication:
    """
    Главное окно приложения (п. 5.1.5.2).
    """

    def __init__(self, root):
        self.root = root
        self.root.title("Нейро-фарм — Агент-поисковик лекарств")
        self.root.geometry("900x700")

        # Скрываем главное окно до авторизации
        self.root.withdraw()

        # Инициализация модулей
        self._init_modules()

        # Данные пользователя
        self.current_user: Optional[Dict[str, Any]] = None

        # Показываем диалог входа
        self._show_login()

        # Окна открываются только один раз
        self._open_windows = {}

    def _init_modules(self):
        """Инициализация всех модулей системы."""
        from auth import DatabaseManager as AuthDB, Authenticator
        from usr_mgr import UserManager
        from site_parser import SiteParser

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

        # Парсеры
        self.dbms_parser = DBMSParser()

        # Загружаем конфигурацию
        config = load_config()
        ftp_cfg = config.get("ftp", {})
        llm_cfg = config.get("llm", {})

        # LLM с параметрами из конфига
        self.llm_manager = LLMManager(
            model_name=llm_cfg.get("model_name", "llama3.1:8b"),
            max_tokens=llm_cfg.get("max_tokens", 512),
            temperature=llm_cfg.get("temperature", 0.7),
            timeout=llm_cfg.get("timeout", 120)
        )

        # FTP-агент с параметрами из конфига
        self.ftp_agent = FTPAgent(
            host=ftp_cfg.get("host", "ftp.aptekamos.ru"),
            port=ftp_cfg.get("port", 21),
            username=ftp_cfg.get("username", "anonymous"),
            password=ftp_cfg.get("password", ""),
            remote_file=ftp_cfg.get("remote_file", "egk_extend306.zip"),
            local_dir=ftp_cfg.get("local_dir", ".")
        )

        # Парсер сайтов
        self.site_parser = SiteParser()

        # Ядро агента
        self.agent = AgentCore(self.med_db, self.llm_manager, self.site_parser)

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
            # Показываем главное окно после успешной авторизации
            self.root.deiconify()  # Или self.root.withdraw(False) – показывает окно
        else:
            self.root.destroy()  # Выход, если авторизация не пройдена

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
                       command=self._show_log_console).pack(side=tk.RIGHT, padx=5)

        if self.current_user["Role"] == "dev":
            ttk.Button(header, text="👥 Пользователи",
                       command=self._show_user_management).pack(side=tk.RIGHT, padx=5)

        ttk.Button(header, text="⚙️ Настройки",
                   command=self._show_settings).pack(side=tk.RIGHT, padx=5)

        # Основной контент (вкладки)
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # Вкладка поиска
        search_panel = SearchPanel(notebook, self.agent, self.dbms_parser, self.current_user["Role"])
        notebook.add(search_panel, text="🔍 Поиск")

        # Вкладка анализа
        analysis_panel = AnalysisPanel(notebook, self.llm_manager, self.dbms_parser, self.current_user)
        analysis_panel.agent = self.agent
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

    def _show_log_console(self):
        """Показ консоли логов (один экземпляр)."""
        if "log_console" in self._open_windows and self._open_windows["log_console"].winfo_exists():
            self._open_windows["log_console"].lift()
            return
        window = LogConsole(self.root)
        self._open_windows["log_console"] = window
        window.protocol("WM_DELETE_WINDOW", lambda: self._close_window("log_console"))

    def _show_user_management(self):
        """Показ управления пользователями (один экземпляр)."""
        if "user_mgmt" in self._open_windows and self._open_windows["user_mgmt"].winfo_exists():
            self._open_windows["user_mgmt"].lift()
            return
        window = UserManagementWindow(self.root, self.user_mgr, self.current_user["ID"])
        self._open_windows["user_mgmt"] = window
        window.protocol("WM_DELETE_WINDOW", lambda: self._close_window("user_mgmt"))

    def _show_settings(self):
        """Показ настроек (один экземпляр)."""
        if "settings" in self._open_windows and self._open_windows["settings"].winfo_exists():
            self._open_windows["settings"].lift()
            return
        window = SettingsWindow(self.root, self.llm_manager, self.ftp_agent)
        self._open_windows["settings"] = window
        window.protocol("WM_DELETE_WINDOW", lambda: self._close_window("settings"))

    def _close_window(self, key: str):
        """Закрытие окна и удаление из словаря."""
        if key in self._open_windows:
            self._open_windows[key].destroy()
            del self._open_windows[key]


# ============= ТОЧКА ВХОДА =============
if __name__ == "__main__":
    root = tk.Tk()
    app = MainApplication(root)
    app.run()