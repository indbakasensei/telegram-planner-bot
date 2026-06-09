import sqlite3
from datetime import datetime

DB_NAME = "planner.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            due_date TEXT,
            due_time TEXT,
            category TEXT DEFAULT 'general',
            done INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def add_task(user_id, title, due_date=None, due_time=None, category='general'):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        INSERT INTO tasks (user_id, title, due_date, due_time, category)
        VALUES (?, ?, ?, ?, ?)
    ''', (user_id, title, due_date, due_time, category))
    conn.commit()
    conn.close()

def get_tasks(user_id, done=0):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        SELECT id, title, due_date, due_time, category
        FROM tasks WHERE user_id=? AND done=?
        ORDER BY due_date ASC, due_time ASC
    ''', (user_id, done))
    tasks = c.fetchall()
    conn.close()
    return tasks

def get_tasks_by_date(user_id, date):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        SELECT id, title, due_date, due_time, category
        FROM tasks WHERE user_id=? AND due_date=? AND done=0
        ORDER BY due_time ASC
    ''', (user_id, date))
    tasks = c.fetchall()
    conn.close()
    return tasks

def get_tasks_by_week(user_id, start_date, end_date):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        SELECT id, title, due_date, due_time, category
        FROM tasks WHERE user_id=? AND due_date BETWEEN ? AND ? AND done=0
        ORDER BY due_date ASC, due_time ASC
    ''', (user_id, start_date, end_date))
    tasks = c.fetchall()
    conn.close()
    return tasks

def mark_done(task_id, user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('UPDATE tasks SET done=1 WHERE id=? AND user_id=?', (task_id, user_id))
    conn.commit()
    conn.close()

def delete_task(task_id, user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('DELETE FROM tasks WHERE id=? AND user_id=?', (task_id, user_id))
    conn.commit()
    conn.close()
