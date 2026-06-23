# Module-level state storage — survives between messages reliably
# context.user_data can get wiped by commands like /ai mid-conversation

_waiting_for_time = {}   # user_id -> True/False
_pending_tasks = {}      # user_id -> task dict
_editing_task = {}       # user_id -> task_id

def set_waiting_time(user_id, pending_task):
    _waiting_for_time[user_id] = True
    _pending_tasks[user_id] = pending_task

def is_waiting_time(user_id):
    return _waiting_for_time.get(user_id, False)

def get_pending_task(user_id):
    return _pending_tasks.get(user_id)

def clear_waiting_time(user_id):
    _waiting_for_time[user_id] = False
    _pending_tasks[user_id] = None

def set_editing(user_id, task_id):
    _editing_task[user_id] = task_id

def get_editing(user_id):
    return _editing_task.get(user_id)

def clear_editing(user_id):
    _editing_task[user_id] = None
