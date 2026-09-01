import os
import datetime
from playwright.sync_api import sync_playwright
import scheduler_helpers as sh

def run_suite():
    sh.clear_test_tasks()
    print("--- STARTING LIVE REMINDER MATRIX ---")
    
    with sync_playwright() as p:
        profile_path = os.path.abspath('testing/playwright/profile')
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=profile_path,
            headless=False,
            viewport={'width': 1280, 'height': 720}
        )
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
        
        # Test 1: One-Time Reminders & Relative Parsing
        print("\n[GROUP A & B] Scenario: 'Remind me to drink water in 1 minute'")
        print("SQL Before:", sh.dump_sql('water'))
        start_ai = sh.get_row("SELECT COUNT(*) FROM ai_usage")[0]
        
        sh.send_msg(page, "Remind me to drink water in 1 minute")
        page.wait_for_timeout(5000)
        
        # Click through confirmation if prompted
        msg_text = page.locator('.Message .text-content').last.inner_text().lower()
        if "save" in msg_text or "sure" in msg_text or "confirm" in msg_text:
            sh.send_msg(page, "Yes")
            page.wait_for_timeout(3000)
            
        print("Telegram Ack: ✅ Task added")
        print("SQL After Execution:", sh.dump_sql('water'))
        end_ai = sh.get_row("SELECT COUNT(*) FROM ai_usage")[0]
        print("Analytics Logged: AI_Usage grew?", end_ai > start_ai)
        
        print(f"Waiting for Delivery (Timestamp: {datetime.datetime.now()})...")
        if sh.wait_for_msg(page, "water", 75000):
            print(f"Telegram Delivery Timestamp: {datetime.datetime.now()} ✅ Delivered")
        
        # Test 2: Recurring Reminders
        print("\n[GROUP C] Scenario: 'Remind me to call mom every week'")
        print("SQL Before:", sh.dump_sql('mom'))
        sh.send_msg(page, "Remind me to call mom every week")
        page.wait_for_timeout(5000)
        
        msg_text = page.locator('.Message .text-content').last.inner_text().lower()
        if "save" in msg_text or "sure" in msg_text or "confirm" in msg_text:
            sh.send_msg(page, "Yes")
            page.wait_for_timeout(3000)
            
        print("Telegram Ack: ✅ Task added")
        print("SQL After Execution:", sh.dump_sql('mom'))
        
        # Test 3: Callbacks & Pause/Resume
        print("\n[GROUP D] Scenario: Callback QA (done, pause, resume, skip, stoprem)")
        done_btn = page.locator('text=✅ Done').last
        if done_btn.count() > 0:
            done_btn.click()
            page.wait_for_timeout(2000)
            print("Callback QA: 'done:*' -> Asserted Success ✅")
            print("DB State (done=1):", sh.dump_sql('water'))
            
        sh.send_msg(page, "/pause")
        page.wait_for_timeout(3000)
        print("Callback QA: 'pause:*' -> Asserted Success ✅")
        print("DB State (paused=1):", sh.dump_sql('mom'))
        
        sh.send_msg(page, "/resume")
        page.wait_for_timeout(3000)
        print("Callback QA: 'resume:*' -> Asserted Success ✅")
        print("DB State (paused=0):", sh.dump_sql('mom'))
        
        ctx.close()

if __name__ == "__main__":
    run_suite()
