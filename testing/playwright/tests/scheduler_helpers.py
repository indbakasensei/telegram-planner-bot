import sqlite3
import datetime
from playwright.sync_api import sync_playwright

DB_NAME = 'test_baka.db'

def get_row(query, params=()):
    try:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute(query, params)
        row = c.fetchone()
        conn.close()
        return row
    except Exception as e:
        return str(e)

def clear_test_tasks():
    conn = sqlite3.connect(DB_NAME)
    conn.execute("DELETE FROM tasks")
    conn.commit()
    conn.close()

def dump_sql(title_substring):
    return get_row("SELECT id, title, due_date, due_time, recurrence_type, done, paused FROM tasks WHERE title LIKE ?", (f'%{title_substring}%',))

def send_msg(page, text):
    page.fill('#editable-message-text', text)
    page.wait_for_timeout(500)
    page.click('button.send, .btn-send, [title="Send Message"], [aria-label="Send Message"], .icon-send', force=True)
    page.keyboard.press('Enter')
    page.wait_for_timeout(4000)

def wait_for_msg(page, text, timeout=80000):
    try:
        page.locator('.Message').filter(has_text=text).last.wait_for(state='visible', timeout=timeout)
        return True
    except:
        return False
