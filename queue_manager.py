import json

class QueueManager:
    def __init__(self):
        self.queue_file = 'queue.json'
        self.register_file = 'register.json'
        self.queue = self.load_queue()
        self.registered_users = self.load_registered_users()

    def load_queue(self):
        try:
            with open(self.queue_file, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def save_queue(self):
        with open(self.queue_file, 'w') as f:
            json.dump(self.queue, f, indent=4)

    def load_registered_users(self):
        try:
            with open(self.register_file, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def save_registered_users(self):
        with open(self.register_file, 'w') as f:
            json.dump(self.registered_users, f, indent=4)

    def is_user_registered(self, user_id):
        return any(user['user_id'] == user_id for user in self.registered_users)

    def get_user_by_display_name(self, display_name):
        for user in self.registered_users:
            if user['display_name'] == display_name:
                return user
        return None

    def update_user_languages(self, display_name, new_languages):
        for user in self.registered_users:
            if user['display_name'] == display_name:
                user['languages'] = new_languages
                self.save_registered_users()
                return True
        return False

    def delete_registered_user(self, display_name):
        self.registered_users = [user for user in self.registered_users if user['display_name'] != display_name]
        self.save_registered_users()

    def register_user(self, user_id, languages, display_name):
        self.registered_users.append({
            'user_id': user_id,
            'display_name': display_name,
            'languages': languages
        })
        self.save_registered_users()

    def is_user_in_queue(self, user_id):
        return any(user['user_id'] == user_id for user in self.queue)

    def add_user_to_queue(self, user_id, display_name, paused=False):
        if not self.is_user_in_queue(user_id):
            self.queue.append({
                'user_id': user_id,
                'display_name': display_name,
                'paused': paused
            })
            self.save_queue()

    def remove_user_from_queue(self, user_id):
        self.queue = [user for user in self.queue if user['user_id'] != user_id]
        self.save_queue()

    def pause_user(self, user_id):
        for user in self.queue:
            if user['user_id'] == user_id:
                user['paused'] = True
                self.save_queue()
                break

    def resume_user(self, user_id):
        for user in self.queue:
            if user['user_id'] == user_id:
                user['paused'] = False
                self.save_queue()
                break

    def move_user_to_top(self, user_id):
        user = next((user for user in self.queue if user['user_id'] == user_id), None)
        if user:
            self.queue.remove(user)
            self.queue.insert(0, user)
            self.save_queue()

    def list_queue(self):
        return self.queue

    def get_user_languages(self, user_id):
        user = next((user for user in self.registered_users if user['user_id'] == user_id), None)
        return user['languages'] if user else []

    def get_first_user_by_language(self, language):
        for user in self.queue:
            if not user['paused']:
                registered_user = self.get_user_by_display_name(user['display_name'])
                if registered_user and language in registered_user['languages']:
                    return user
        return None

    def get_user_id_by_display_name(self, display_name):
        user = self.get_user_by_display_name(display_name)
        return user['user_id'] if user else None

    def get_display_name(self, user_id):
        user = next((user for user in self.registered_users if user['user_id'] == user_id), None)
        return user['display_name'] if user else None
    
    def get_first_user(self):
        return self.queue[0] if self.queue else None