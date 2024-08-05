import threading
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv
import os
import logging

# Загрузка переменных окружения из .env файла
load_dotenv()

class SheetsManager:
    def __init__(self):
        # Получение идентификатора таблицы из переменной окружения
        spreadsheet_id = os.getenv('GOOGLE_SHEET_ID')
        
        if not spreadsheet_id:
            raise ValueError("GOOGLE_SHEET_ID not found in environment variables.")
        
        # Укажите путь к вашему файлу учетных данных
        creds_file = '/credentials.json'
        scopes = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]

        # Создайте учетные данные с необходимыми скопами
        creds = Credentials.from_service_account_file(creds_file, scopes=scopes)
        self.client = gspread.authorize(creds)
        self.sheet = self.client.open_by_key(spreadsheet_id).sheet1

    def find_empty_row(self):
        """Находит первую пустую строку в Google Sheet."""
        all_values = self.sheet.get_all_values()

        # Ищем первую пустую строку (после заполненных строк)
        row_index = len(all_values) + 1

        # Проверяем пустые строки
        for idx, row in enumerate(all_values):
            if not any(row[:5]):  # Проверяем, если все пять столбцов пусты
                row_index = idx + 1
                break

        return row_index

    def add_task_to_sheet(self, timestamp, message, language, display_name):
        """Добавляет задачу в Google Sheet с данными."""
        try:
            # Находим первую пустую строку
            row_index = self.find_empty_row()

            # Добавляем данные в найденную пустую строку
            self.sheet.insert_row([timestamp, '', message, language, display_name], index=row_index)
        
        except Exception as e:
            raise Exception(f"Error adding task to sheet: {e}")

    def add_task_to_sheet_async(self, timestamp, message, language, display_name):
        """Запускает добавление задачи в Google Sheet в фоновом режиме."""
        
        def task():
            try:
                self.add_task_to_sheet(timestamp, message, language, display_name)
            except Exception as e:
                logging.error(f"Failed to add task to Google Sheet: {e}")

        # Запуск в отдельном потоке
        thread = threading.Thread(target=task)
        thread.start()
