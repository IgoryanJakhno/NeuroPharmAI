"""
Скрипт сборки исполняемого файла с помощью PyInstaller.
Запуск: python build.py
"""

import PyInstaller.__main__
import os
import shutil
import sys
import dbfread  # <-- импортируем для получения пути

# Путь к основному скрипту
MAIN_SCRIPT = "gui_mgr.py"

# Дополнительные файлы для включения в сборку
ADDITIONAL_FILES = [
    ("prompt_templates.json", "."),  # (источник, назначение в папке с exe)
]

# Иконка (если есть)
ICON_FILE = "assets/icon.ico"  # опционально

def clean_build():
    """Удаляет старые папки сборки."""
    for folder in ["build", "dist"]:
        if os.path.exists(folder):
            shutil.rmtree(folder)
    print("🧹 Очистка завершена.")

def build():
    clean_build()
    print("🚀 Сборка исполняемого файла...")

    # Находим путь к папке с dbfread
    dbfread_path = os.path.dirname(dbfread.__file__)
    print(f"📦 dbfread найден по пути: {dbfread_path}")

    args = [
        MAIN_SCRIPT,
        "--name=NeuroPharm",
        "--onefile",          # Один .exe файл
        "--windowed",         # Без консоли (графическое приложение)
        "--add-data=prompt_templates.json;.",  # Для Windows разделитель ";"
        f"--add-data={dbfread_path};dbfread",  # <-- добавляем всю папку dbfread
        "--hidden-import=tkinter",
        "--hidden-import=dbfread",
        "--hidden-import=requests",
        "--hidden-import=bs4",
        "--hidden-import=sqlite3",
    ]

    if os.path.exists(ICON_FILE):
        args.append(f"--icon={ICON_FILE}")

    # Убираем --collect-all=dbfread, так как он не работает для модулей

    # Запуск PyInstaller
    PyInstaller.__main__.run(args)
    print("✅ Сборка завершена! Файл находится в папке dist/NeuroPharm.exe")

if __name__ == "__main__":
    build()