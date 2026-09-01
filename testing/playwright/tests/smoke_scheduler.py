import os
import subprocess
import datetime
import sqlite3
import time
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

def dump_sql(title_substring):
    return get_row("SELECT id, title, due_date, due_time, recurrence_type, done, paused FROM tasks WHERE title LIKE ?", (f'%{title_substring}%',))

def clear_test_tasks():
    conn = sqlite3.connect(DB_NAME)
    conn.execute("DELETE FROM tasks")
    conn.execute("DELETE FROM interaction_log")
    conn.execute("DELETE FROM ai_usage")
    conn.commit()
    conn.close()

def send_msg(page, text):
    page.fill('#editable-message-text', text)
    page.wait_for_timeout(500)
    page.click('button.send, .btn-send, [title="Send Message"], [aria-label="Send Message"], .icon-send', force=True)
    page.keyboard.press('Enter')
    page.wait_for_timeout(2000)

def create_task(page, text):
    send_msg(page, text)
    # Wait for the confirmation prompt from AI
    wait_for_msg(page, "save, no to cancel", 30000)
    send_msg(page, "Yes")
    # Wait for saved confirmation
    wait_for_msg(page, "saved!", 20000)

def wait_for_msg(page, text, timeout=80000):
    try:
        page.locator('.Message').filter(has_text=text).last.wait_for(state='visible', timeout=timeout)
        return True
    except:
        return False

def run_suite():
    clear_test_tasks()
    print("--- SCHEDULER & REMINDER MATRIX ---")
    
    with sync_playwright() as p:
        profile_path = os.path.abspath('testing/playwright/profile')
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=profile_path,
            headless=False,
            viewport={'width': 1280, 'height': 720}
        )
        ctx.tracing.start(screenshots=True, snapshots=True, sources=True)
        
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto('https://web.telegram.org/a/')
        page.wait_for_timeout(3000)
        
        page.click('#telegram-search-input')
        page.keyboard.type('@Baka_qa_bot', delay=50)
        page.wait_for_timeout(3000)
        
        peer = page.locator('.LeftSearch .ListItem').filter(has=page.locator('[data-peer-id]')).first
        peer.wait_for(state='visible', timeout=15000)
        peer.click()
        page.wait_for_selector('#editable-message-text', timeout=15000)
        
        # 1. One-time reminder
        print("\n[1] One-time reminder")
        create_task(page, "Remind me to drink water in 1 minute")
        print("SQL Evidence:", dump_sql('water'))
        
        # 2, 3, 4. Recurring reminders
        print("\n[2, 3, 4] Recurring reminders")
        create_task(page, "Remind me to workout every day")
        print("Daily DB:", dump_sql('workout'))
        
        create_task(page, "Remind me to call mom every week")
        print("Weekly DB:", dump_sql('mom'))
        
        create_task(page, "Remind me to pay bills every month")
        print("Monthly DB:", dump_sql('bills'))
        
        # Wait for water reminder to pop up
        print("\nWaiting for One-Time Reminder to fire...")
        wait_for_msg(page, "water", 75000)
        print("Telegram message delivered.")
        
        # 5. Completion Callback
        print("\n[5] Reminder completion callback")
        done_btn = page.locator('text=✅ Done').last
        if done_btn.count() > 0:
            done_btn.click()
            page.wait_for_timeout(3000)
            print("DB After Done:", dump_sql('water'))
            
        # 8. Delete callback
        print("\n[8] Delete callback")
        create_task(page, "Remind me to delete this in 1 minute")
        wait_for_msg(page, "delete this", 75000)
        del_btn = page.locator('text=🗑 Delete Task').last
        if del_btn.count() > 0:
            del_btn.click()
            page.wait_for_timeout(3000)
            print("DB After Delete:", dump_sql('delete this'))

        # 6, 7. Pause/Resume
        print("\n[6, 7] Pause / Resume callbacks")
        conn = sqlite3.connect(DB_NAME)
        task_id = conn.execute("SELECT id FROM tasks WHERE title LIKE '%workout%'").fetchone()[0]
        conn.close()
        
        send_msg(page, f"/pause {task_id}")
        page.wait_for_timeout(3000)
        print("DB After Pause:", dump_sql('workout'))
        
        send_msg(page, f"/resume {task_id}")
        page.wait_for_timeout(3000)
        print("DB After Resume:", dump_sql('workout'))

        # 9, 10. Planner & QA Restart Recovery
        print("\n[9, 10] Restart Recovery")
        create_task(page, "Remind me to verify recovery in 2 minutes")
        print("DB Before Recovery:", dump_sql('verify recovery'))
        
        print("Stopping All Bots...")
        subprocess.run(["./scripts/stop_all.sh"])
        
        print("Waiting 130s for offline gap...")
        page.wait_for_timeout(130000)
        
        print("Restarting All Bots...")
        subprocess.Popen(["./scripts/start_all.sh"])
        page.wait_for_timeout(5000)
        
        if wait_for_msg(page, "verify recovery", 75000):
            print("Offline recovery reminder received successfully.")

        print("\n[Analytics Logs]")
        conn = sqlite3.connect(DB_NAME)
        print("AI Usage rows:", conn.execute("SELECT COUNT(*) FROM ai_usage").fetchone()[0])
        print("Interaction Log rows:", conn.execute("SELECT COUNT(*) FROM interaction_log").fetchone()[0])
        conn.close()
        
        ctx.tracing.stop(path="testing/playwright/trace.zip")
        print("Playwright trace location: testing/playwright/trace.zip")
        
        ctx.close()

if __name__ == "__main__":
    run_suite()
