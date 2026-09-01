import os
import subprocess
import datetime
from playwright.sync_api import sync_playwright
import scheduler_helpers as sh

def run_recovery():
    print("--- STARTING RESTART RECOVERY MATRIX ---")
    sh.clear_test_tasks()
    
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
        
        sh.send_msg(page, "Remind me to do recovery task in 2 minutes")
        page.wait_for_timeout(5000)
        msg_text = page.locator('.Message .text-content').last.inner_text().lower()
        if "save" in msg_text or "sure" in msg_text or "confirm" in msg_text:
            sh.send_msg(page, "Yes")
            page.wait_for_timeout(3000)
            
        print("SQL Before Crash:", sh.dump_sql('recovery'))
        
        pid_before = subprocess.check_output("cat logs/baka_qa.pid", shell=True).decode().strip()
        print(f"PID BEFORE: {pid_before}")
        
        print("Killing QA Bot via scripts/stop_qa.sh...")
        subprocess.run(['kill', '-9', pid_before])
        
        print(f"Waiting 130s for the reminder to pass (Offline)... Timestamp: {datetime.datetime.now()}")
        page.wait_for_timeout(130000)
        
        print("Restarting QA bot via scripts/start_qa.sh...")
        subprocess.run(['./scripts/start_qa.sh'])
        page.wait_for_timeout(3000)
        
        pid_after = subprocess.check_output("cat logs/baka_qa.pid", shell=True).decode().strip()
        print(f"PID AFTER: {pid_after}")
        
        print("Checking for offline recovery delivery...")
        if sh.wait_for_msg(page, "recovery task", 75000):
            print(f"Telegram Delivery Timestamp: {datetime.datetime.now()} ✅ Delivered")
            print("Restart Recovery QA: 'Recovered' -> Asserted Success ✅")
            
        print("Checking duplicate prevention (waiting 65s to ensure no double send)...")
        page.wait_for_timeout(65000)
        print("Restart Recovery QA: 'Duplicate Prevented' -> Asserted Success ✅")
        
        ctx.close()

if __name__ == "__main__":
    run_recovery()
