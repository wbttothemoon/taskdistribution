import os
import json
import shlex
import logging
from flask import Flask, request, jsonify
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from dotenv import load_dotenv
from queue_manager import QueueManager
from sheets_manager import SheetsManager
from datetime import datetime
import pytz

load_dotenv()

SLACK_BOT_TOKEN = os.getenv('SLACK_BOT_TOKEN')
GENERAL_CHANNEL_ID = os.getenv('GENERAL_CHANNEL_ID')
ALLOWED_USER_GROUP = os.getenv('ALLOWED_USER_GROUP')
AWAITING_TASKS_FILE = 'awaiting_tasks.json'

app = Flask(__name__)
client = WebClient(token=SLACK_BOT_TOKEN)
queue_manager = QueueManager()
sheets_manager = SheetsManager()

def get_user_groups(user_id):
    try:
        response = client.usergroups_users_list(usergroup=ALLOWED_USER_GROUP)
        return response['users']
    except SlackApiError as e:
        return []

def user_in_allowed_group(user_id):
    user_groups = get_user_groups(user_id)
    return user_id in user_groups

def get_display_name(user_id):
    try:
        user_info = client.users_info(user=user_id)
        display_name = user_info['user']['profile'].get('display_name') or user_info['user']['profile'].get('real_name')
        return display_name
    except SlackApiError as e:
        return None

@app.route('/queue', methods=['POST'])
def handle_queue_command():
    data = request.form
    command_text = data.get('text').strip()
    user_id = data.get('user_id')
    trigger_id = data.get('trigger_id')
    try:
        args = shlex.split(command_text)
    except ValueError as e:
        return jsonify({'response_type': 'ephemeral', 'text': 'Error parsing command. Ensure your message and language are properly quoted.'})

    command = args[0]

    if command == 'register':
        return handle_register_command(user_id, trigger_id)
    elif command == 'list':
        return handle_list_command(user_id)
    elif command == 'add':
        return handle_add_command(user_id)
    elif command == 'remove':
        return handle_remove_command(user_id)
    elif command == 'pause':
        return handle_pause_command(user_id, trigger_id)
    elif command == 'resume':
        return handle_resume_command(user_id)
    elif command == 'deletereg':
        return handle_deletereg_command(user_id, args)
    elif command == 'editreg':
        return handle_editreg_command(user_id, args, trigger_id)
    elif command == 'removeop':
        return handle_removeop_command(user_id, args)
    elif command == 'taskline':
        return handle_taskline_command()
    else:
        return jsonify({'response_type': 'ephemeral', 'text': 'Incorrect usage of the command.'})

@app.route('/createtask', methods=['POST'])
def handle_create_command():
    data = request.form
    command_text = data.get('text', '').strip()
    user_id = data.get('user_id')

    try:
        args = shlex.split(command_text)
    except ValueError as e:
        logging.error(f"Error parsing command: {e}")
        return jsonify({'response_type': 'ephemeral', 'text': 'Error parsing command. Ensure your message and language are properly quoted.'})

    if len(args) != 2:
        return jsonify({'response_type': 'ephemeral', 'text': 'Incorrect usage of the command. You must provide both a message and a language.'})

    message = args[0]
    language = args[1]

    # Обработать задачу и вернуть результат
    result = handle_create_task_command(user_id, message, language)
    return jsonify(result)

@app.route('/forcetask', methods=['POST'])
def handle_force_task_command():
    data = request.form
    command_text = data.get('text', '').strip()
    user_id = data.get('user_id')

    try:
        args = shlex.split(command_text)
    except ValueError as e:
        logging.error(f"Error parsing command: {e}")
        return jsonify({'response_type': 'ephemeral', 'text': 'Error parsing command. Ensure your message and language are properly quoted.'})

    if len(args) != 2:
        return jsonify({'response_type': 'ephemeral', 'text': 'Incorrect usage of the command. You must provide both a message and a language.'})

    message = args[0]
    language = args[1]

    # Обработать задачу и вернуть результат
    result = handle_force_task_command_logic(user_id, message, language)
    return jsonify(result)

@app.route('/assigntask', methods=['POST'])
def handle_assignetask_command():
    data = request.form
    command_text = data.get('text').strip()

    try:
        args = shlex.split(command_text)
    except ValueError as e:
        return jsonify({'response_type': 'ephemeral', 'text': 'Error parsing command. Ensure your message and language are properly quoted.'})

    if len(args) == 3:
        message = args[0]
        target_user_display_name = args[1].replace('@', '').strip()
        language = args[2]
        return handle_assign_task_command(target_user_display_name, message, language)
    else:
        return jsonify({'response_type': 'ephemeral', 'text': 'Incorrect usage of the command.'})

def handle_removeop_command(user_id, args):
    if len(args) != 2:
        return jsonify({'response_type': 'ephemeral', 'text': 'Please provide the display name in quotes.'})

    if not is_user_in_allowed_group(user_id):
        return jsonify({'response_type': 'ephemeral', 'text': 'You do not have permission to use this command.'})

    target_display_name = args[1].strip('"')

    user_to_remove = queue_manager.get_user_by_display_name(target_display_name)
    if not user_to_remove or not queue_manager.is_user_in_queue(user_to_remove['user_id']):
        return jsonify({'response_type': 'ephemeral', 'text': f'Operator with display name {target_display_name} not found in queue.'})

    # Удаляем пользователя из очереди
    queue_manager.remove_user_from_queue(user_to_remove['user_id'])
    return jsonify({'response_type': 'ephemeral', 'text': f'<@{user_to_remove["user_id"]}> [{", ".join(user_to_remove["languages"])}] has been removed from the queue.'})

@app.route('/give-task-from-awaiting-list', methods=['POST'])
def handle_give_task_from_awaiting_list():
    data = request.form
    user_id = data.get('user_id')
    command_text = data.get('text', '').strip()

    try:
        # Разбиваем команду на номер задачи и display_name
        args = shlex.split(command_text)
        if len(args) != 2:
            return jsonify({'response_type': 'ephemeral', 'text': 'Invalid command format. Use: /give-task-from-awaiting-list task_number "display_name".'})

        task_number = int(args[0].strip()) - 1
        target_display_name = args[1].strip('"')
    except ValueError:
        return jsonify({'response_type': 'ephemeral', 'text': 'Invalid task number. Please provide a valid number from the awaiting tasks list.'})

    awaiting_tasks = load_awaiting_tasks()
    
    # Проверяем, существует ли задача с таким номером
    if task_number < 0 or task_number >= len(awaiting_tasks):
        return jsonify({'response_type': 'ephemeral', 'text': 'Task number out of range. Please provide a valid number from the awaiting tasks list.'})

    # Получаем задачу по номеру
    task = awaiting_tasks[task_number]
    message = task['message']
    language = task['language']

    # Находим пользователя по display_name
    user_to_assign = queue_manager.get_user_by_display_name(target_display_name)
    if not user_to_assign:
        return jsonify({'response_type': 'ephemeral', 'text': f'User with display name {target_display_name} not found.'})

    target_user_id = user_to_assign['user_id']

    try:
        # Отправить сообщение о задаче в Slack
        client.chat_postMessage(
            channel=GENERAL_CHANNEL_ID,
            text=f"{message} <@{target_user_id}> ({language})"
        )

        # Получаем текущее время в часовом поясе Украины
        ukraine_tz = pytz.timezone('Europe/Kyiv')
        current_time = datetime.now(ukraine_tz).strftime('%Y-%m-%d %H:%M:%S')

        # Запускаем добавление задачи в Google Sheet в фоне
        sheets_manager.add_task_to_sheet_async(current_time, message, language, target_display_name)

        # Удалить пользователя из очереди, если он есть
        if queue_manager.is_user_in_queue(target_user_id):
            queue_manager.remove_user_from_queue(target_user_id)

        # Удаляем задачу из awaiting_tasks.json
        awaiting_tasks.pop(task_number)
        save_awaiting_tasks(awaiting_tasks)

        return jsonify({'response_type': 'ephemeral', 'text': f'Task assigned to {target_display_name}: {message} ({language}).'})
    except SlackApiError as e:
        logging.error(f"Failed to distribute task: {e.response['error']}")
        return jsonify({'response_type': 'ephemeral', 'text': 'Failed to distribute task.'})


def handle_register_command(user_id, trigger_id):
    if queue_manager.is_user_registered(user_id):
        return jsonify({'response_type': 'ephemeral', 'text': 'You are already registered.'})

    display_name = get_display_name(user_id)
    if not display_name:
        return jsonify({'response_type': 'ephemeral', 'text': 'Failed to retrieve display name.'})

    try:
        client.views_open(
            trigger_id=trigger_id,
            view={
                "type": "modal",
                "callback_id": "language_selection",
                "title": {"type": "plain_text", "text": "Language Selection"},
                "submit": {"type": "plain_text", "text": "Submit"},
                "blocks": [
                    {
                        "type": "input",
                        "block_id": "languages",
                        "element": {
                            "type": "checkboxes",
                            "options": [
                                {"text": {"type": "plain_text", "text": "RU"}, "value": "RU"},
                                {"text": {"type": "plain_text", "text": "UA"}, "value": "UA"},
                                {"text": {"type": "plain_text", "text": "EN"}, "value": "EN"},
                                {"text": {"type": "plain_text", "text": "KA"}, "value": "KA"},
                                {"text": {"type": "plain_text", "text": "TR"}, "value": "TR"},
                                {"text": {"type": "plain_text", "text": "PL"}, "value": "PL"},
                                {"text": {"type": "plain_text", "text": "ES"}, "value": "ES"},
                                {"text": {"type": "plain_text", "text": "PT"}, "value": "PT"}
                            ],
                            "action_id": "language_selection"
                        },
                        "label": {"type": "plain_text", "text": "Select languages"}
                    }
                ]
            }
        )
        return ''
    except SlackApiError as e:
        return jsonify({'response_type': 'ephemeral', 'text': 'Failed to open modal.'})

def handle_taskline_command():
    awaiting_tasks = load_awaiting_tasks()
    if not awaiting_tasks:
        return jsonify({'response_type': 'ephemeral', 'text': 'No tasks in the awaiting list.'})

    task_list = "\n".join([f"{i + 1}. Message: {task['message']}, Language: {task['language']}" for i, task in enumerate(awaiting_tasks)])
    return jsonify({'response_type': 'ephemeral', 'text': f'Awaiting tasks:\n{task_list}'})


def handle_list_command(user_id):
    queue = queue_manager.list_queue()
    formatted_queue = "\n".join([
        f"<@{item['user_id']}> (paused) [{', '.join(queue_manager.get_user_languages(item['user_id']))}]" if item['paused'] else f"<@{item['user_id']}> [{', '.join(queue_manager.get_user_languages(item['user_id']))}]"
        for item in queue
    ])
    return jsonify({'response_type': 'ephemeral', 'text': f'Current Queue:\n{formatted_queue}'})

def handle_add_command(user_id):
    if queue_manager.is_user_in_queue(user_id):
        return jsonify({'response_type': 'ephemeral', 'text': 'You are already in the queue.'})

    try:
        # Получаем информацию о пользователе из Slack
        user_info = client.users_info(user=user_id)
        display_name = user_info['user']['profile']['display_name'] or user_info['user']['name']
    except SlackApiError as e:
        logging.error(f"Error fetching user info: {e.response['error']}")
        return jsonify({'response_type': 'ephemeral', 'text': 'Failed to fetch user info.'})

    languages = queue_manager.get_user_languages(user_id)

    # Проверяем ожидающие задачи
    awaiting_tasks = load_awaiting_tasks()
    assigned_tasks = []

    for task in awaiting_tasks:
        if task['language'] in languages:
            try:
                # Отправить сообщение о задаче в Slack
                client.chat_postMessage(
                    channel=GENERAL_CHANNEL_ID,
                    text=f"{task['message']} <@{user_id}> ({task['language']})"
                )

                # Получаем текущее время в часовом поясе Украины
                ukraine_tz = pytz.timezone('Europe/Kyiv')
                current_time = datetime.now(ukraine_tz).strftime('%Y-%m-%d %H:%M:%S')

                # Запускаем добавление задачи в Google Sheet в фоне
                sheets_manager.add_task_to_sheet_async(current_time, task['message'], task['language'], display_name)

                # Удалить пользователя из очереди
                queue_manager.remove_user_from_queue(user_id)

                # Добавляем задачу в список назначенных задач
                assigned_tasks.append(task)
                break  # Назначаем только одну задачу и выходим из цикла
            except SlackApiError as e:
                logging.error(f"Failed to assign awaiting task: {e.response['error']}")

    # Удаляем назначенные задачи из списка ожидающих задач
    if assigned_tasks:
        for task in assigned_tasks:
            awaiting_tasks.remove(task)
        save_awaiting_tasks(awaiting_tasks)
        return jsonify({'response_type': 'ephemeral', 'text': 'Task from awaiting list assigned to you.'})

    # Если задачи не были назначены, добавляем пользователя в очередь
    queue_manager.add_user_to_queue(user_id, display_name)
    return client.chat_postMessage(channel=GENERAL_CHANNEL_ID, text=f"<@{user_id}> [{', '.join(languages)}] added to the queue successfully.")


def handle_remove_command(user_id):
    if not queue_manager.is_user_in_queue(user_id):
        return jsonify({'response_type': 'ephemeral', 'text': 'You are not in the queue.'})

    queue_manager.remove_user_from_queue(user_id)
    languages = queue_manager.get_user_languages(user_id)
    return client.chat_postMessage(channel=GENERAL_CHANNEL_ID, text=f"<@{user_id}> [{', '.join(languages)}] removed from queue successfully.")

def handle_pause_command(user_id, trigger_id):
    if not queue_manager.is_user_in_queue(user_id):
        return jsonify({'response_type': 'ephemeral', 'text': 'You are not in the queue.''.'})

    try:
        client.views_open(
            trigger_id=trigger_id,
            view={
                "type": "modal",
                "callback_id": "pause_reason",
                "title": {"type": "plain_text", "text": "Pause Queue"},
                "submit": {"type": "plain_text", "text": "Submit"},
                "blocks": [
                    {
                        "type": "input",
                        "block_id": "reason",
                        "element": {
                            "type": "plain_text_input",
                            "action_id": "reason_input",
                            "placeholder": {"type": "plain_text", "text": "Enter reason for pausing"}
                        },
                        "label": {"type": "plain_text", "text": "Reason"}
                    }
                ]
            }
        )
        return ''
    except SlackApiError as e:
        return jsonify({'response_type': 'ephemeral', 'text': 'Failed to open modal.'})

def handle_resume_command(user_id):
    if not queue_manager.is_user_in_queue(user_id):
        return jsonify({'response_type': 'ephemeral', 'text': 'You are not in the queue.'})

    queue_manager.resume_user(user_id)
    languages = queue_manager.get_user_languages(user_id)
    return client.chat_postMessage(channel=GENERAL_CHANNEL_ID, text=f"<@{user_id}> [{', '.join(languages)}] resumed in the queue.")

def handle_deletereg_command(user_id, args):
    if not user_in_allowed_group(user_id):
        return jsonify({'response_type': 'ephemeral', 'text': 'You do not have permission to perform this action.'})

    if len(args) != 2:
        return jsonify({'response_type': 'ephemeral', 'text': 'Please provide the display name in quotes.'})

    target_display_name = args[1].strip('"')

    if not queue_manager.get_user_by_display_name(target_display_name):
        return jsonify({'response_type': 'ephemeral', 'text': f'Operator with display name {target_display_name} not found.'})

    queue_manager.delete_registered_user(target_display_name)
    return jsonify({'response_type': 'ephemeral', 'text': f'Operator {target_display_name} has been successfully unregistered.'})

def handle_editreg_command(user_id, args, trigger_id):
    if not user_in_allowed_group(user_id):
        return jsonify({'response_type': 'ephemeral', 'text': 'You do not have permission to perform this action.'})

    if len(args) != 2:
        return jsonify({'response_type': 'ephemeral', 'text': 'Please provide the display name in quotes.'})

    target_display_name = args[1].strip('"')

    user = queue_manager.get_user_by_display_name(target_display_name)
    if not user:
        return jsonify({'response_type': 'ephemeral', 'text': f'Operator with display name {target_display_name} not found.'})

    try:
        client.views_open(
            trigger_id=trigger_id,
            view={
                "type": "modal",
                "callback_id": "edit_language_selection",
                "title": {"type": "plain_text", "text": "Edit Languages"},
                "submit": {"type": "plain_text", "text": "Submit"},
                "blocks": [
                    {
                        "type": "input",
                        "block_id": "languages",
                        "element": {
                            "type": "checkboxes",
                            "options": [
                                {"text": {"type": "plain_text", "text": "RU"}, "value": "RU"},
                                {"text": {"type": "plain_text", "text": "UA"}, "value": "UA"},
                                {"text": {"type": "plain_text", "text": "EN"}, "value": "EN"},
                                {"text": {"type": "plain_text", "text": "KA"}, "value": "KA"},
                                {"text": {"type": "plain_text", "text": "TR"}, "value": "TR"},
                                {"text": {"type": "plain_text", "text": "PL"}, "value": "PL"},
                                {"text": {"type": "plain_text", "text": "ES"}, "value": "ES"},
                                {"text": {"type": "plain_text", "text": "PT"}, "value": "PT"}
                            ],
                            "action_id": "language_selection",
                            "initial_options": [
                                {"text": {"type": "plain_text", "text": lang}, "value": lang}
                                for lang in user['languages']
                            ]
                        },
                        "label": {"type": "plain_text", "text": "Select languages"}
                    }
                ],
                "private_metadata": target_display_name
            }
        )
        return ''
    except SlackApiError as e:
        return jsonify({'response_type': 'ephemeral', 'text': 'Failed to open modal.'})

def handle_create_task_command(user_id, message, language):
    # Найти первого пользователя в очереди с указанным языком
    first_user = queue_manager.get_first_user_by_language(language)
    
    if first_user:
        try:
            # Отправить сообщение о задаче в Slack
            client.chat_postMessage(
                channel=GENERAL_CHANNEL_ID,
                text=f"{message} <@{first_user['user_id']}> ({language})"
            )
            display_name = first_user['display_name']

            # Получаем текущее время в часовом поясе Украины
            ukraine_tz = pytz.timezone('Europe/Kyiv')
            current_time = datetime.now(ukraine_tz).strftime('%Y-%m-%d %H:%M:%S')

            # Запускаем добавление задачи в Google Sheet в фоне
            sheets_manager.add_task_to_sheet_async(current_time, message, language, display_name)

            # Удалить пользователя из очереди
            queue_manager.remove_user_from_queue(first_user['user_id'])
            return {'response_type': 'ephemeral', 'text': 'Task created and assigned. Operator has been removed from the queue.'}
        except SlackApiError as e:
            logging.error(f"Failed to create task: {e.response['error']}")
            return {'response_type': 'ephemeral', 'text': 'Failed to create task.'}
    else:
        # Добавляем задачу в список ожидающих задач
        add_task_to_awaiting(message, language)
        client.chat_postMessage(channel=GENERAL_CHANNEL_ID, text=f"<!here> Oops, looks like we need an operator with this language ({language}). Please, if anyone is available, join the queue using /queue add.")
        return {'response_type': 'ephemeral', 'text': 'No operator available for the selected language. Task has been added to the awaiting list.'}

def handle_force_task_command_logic(user_id, message, language):
    # Найти первого пользователя в очереди
    first_user = queue_manager.get_first_user()
    
    if first_user:
        try:
            # Отправить сообщение о задаче в Slack
            client.chat_postMessage(
                channel=GENERAL_CHANNEL_ID,
                text=f"{message} <@{first_user['user_id']}> ({language}) (Forced task)"
            )
            display_name = first_user['display_name']

            # Получаем текущее время в часовом поясе Украины
            ukraine_tz = pytz.timezone('Europe/Kyiv')
            current_time = datetime.now(ukraine_tz).strftime('%Y-%m-%d %H:%M:%S')

            # Запускаем добавление задачи в Google Sheet в фоне
            sheets_manager.add_task_to_sheet_async(current_time, message, language, display_name)

            # Удалить пользователя из очереди
            queue_manager.remove_user_from_queue(first_user['user_id'])
            return {'response_type': 'ephemeral', 'text': 'Forced task created and assigned. Operator has been removed from the queue.'}
        except SlackApiError as e:
            logging.error(f"Failed to create forced task: {e.response['error']}")
            return {'response_type': 'ephemeral', 'text': 'Failed to create forced task.'}
    else:
        # Сообщение, если нет доступного пользователя
        client.chat_postMessage(
            channel=GENERAL_CHANNEL_ID, 
            text=f"<!here> Oops, there are no users available in the queue. Please, if anyone is available, join the queue using /queue add."
        )
        return {'response_type': 'ephemeral', 'text': 'No users available in the queue.'}

def handle_assign_task_command(target_user_display_name, message, language):
    # Получение user_id по display_name
    target_user_id = queue_manager.get_user_id_by_display_name(target_user_display_name)

    if not target_user_id:
        logging.debug(f"Operator with display name '{target_user_display_name}' not found in register.")
        return jsonify({'response_type': 'ephemeral', 'text': f"Operator with display name {target_user_display_name} not found in register."})

    try:
        client.chat_postMessage(
            channel=GENERAL_CHANNEL_ID,
            text=f"{message} <@{target_user_id}> {language}"
        )
        display_name = queue_manager.get_display_name(target_user_id)

        # Получаем текущее время в часовом поясе Украины
        ukraine_tz = pytz.timezone('Europe/Kyiv')
        current_time = datetime.now(ukraine_tz).strftime('%Y-%m-%d %H:%M:%S')

        # Запускаем добавление задачи в Google Sheet в фоне
        sheets_manager.add_task_to_sheet_async(current_time, message, language, display_name)

        if queue_manager.is_user_in_queue(target_user_id):
            queue_manager.remove_user_from_queue(target_user_id)
        return jsonify({'response_type': 'ephemeral', 'text': 'Task assigned successfully.'})
    except SlackApiError as e:
        logging.error(f"Failed to assign task: {e.response['error']}")
        return jsonify({'response_type': 'ephemeral', 'text': 'Failed to assign task.'})

def add_task_to_sheet(display_name, message, language):
    try:
        ukraine_tz = pytz.timezone('Europe/Kyiv')
        current_time = datetime.now(ukraine_tz).strftime('%Y-%m-%d %H:%M:%S')
        sheets_manager.add_task_to_sheet(current_time, message, language, display_name)
    except Exception as e:
        logging.error(f"Failed to add task to Google Sheet: {e}")

def is_user_in_allowed_group(user_id):
    try:
        # Получаем информацию о пользователе
        usergroups_response = client.usergroups_users_list(usergroup=ALLOWED_USER_GROUP)
        allowed_users = usergroups_response['users']

        return user_id in allowed_users
    except SlackApiError as e:
        logging.error(f"Error fetching user groups: {e.response['error']}")
        return False

def load_awaiting_tasks():
    """Загружает ожидающие задачи из файла."""
    try:
        with open(AWAITING_TASKS_FILE, 'r') as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def save_awaiting_tasks(tasks):
    """Сохраняет ожидающие задачи в файл."""
    with open(AWAITING_TASKS_FILE, 'w') as file:
        json.dump(tasks, file, indent=4)

def add_task_to_awaiting(message, language):
    """Добавляет задачу в список ожидающих задач."""
    tasks = load_awaiting_tasks()
    tasks.append({'message': message, 'language': language})
    save_awaiting_tasks(tasks)
       
@app.route('/interactivity', methods=['POST'])
def handle_interactivity():
    payload = json.loads(request.form.get('payload'))

    if payload['type'] == 'view_submission':
        view = payload['view']
        callback_id = view['callback_id']
        user_id = payload['user']['id']

        if callback_id == 'language_selection':
            selected_languages = [option['value'] for option in view['state']['values']['languages']['language_selection']['selected_options']]
            display_name = get_display_name(user_id)
            if not display_name:
                return jsonify({'response_type': 'ephemeral', 'text': 'Failed to retrieve display name.'})

            queue_manager.register_user(user_id, selected_languages, display_name)
            return client.chat_postMessage(channel=GENERAL_CHANNEL_ID, text=f"<@{user_id}> [{', '.join(selected_languages)}] has been successfully registered.")
        
        elif callback_id == 'edit_language_selection':
            target_display_name = view['private_metadata']
            selected_languages = [option['value'] for option in view['state']['values']['languages']['language_selection']['selected_options']]
            user = queue_manager.get_user_by_display_name(target_display_name)
            if user:
                user_id = user['user_id']
                if not queue_manager.update_user_languages(target_display_name, selected_languages):
                    return jsonify({'response_type': 'ephemeral', 'text': 'Failed to update languages.'})
                return client.chat_postMessage(channel=GENERAL_CHANNEL_ID, text=f"<@{user_id}> languages have been updated to: [{', '.join(selected_languages)}].")

        elif callback_id == 'pause_reason':
            reason = view['state']['values']['reason']['reason_input']['value']
            if not reason.strip():
                return jsonify({'response_action': 'errors', 'errors': {'reason': 'Reason is required.'}})

            queue_manager.pause_user(user_id)
            languages = queue_manager.get_user_languages(user_id)
            return client.chat_postMessage(channel=GENERAL_CHANNEL_ID, text=f"<@{user_id}> [{', '.join(languages)}] paused in queue. Reason: \"{reason}\"")

    return jsonify({})

if __name__ == '__main__':
    app.run(debug=True)
