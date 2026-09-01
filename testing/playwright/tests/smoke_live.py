import os
import time
import subprocess
from playwright.sync_api import sync_playwright

def ensure_qa_bot():
    print("Checking QA bot status...")
    status = subprocess.run(['./scripts/status.sh'], capture_output=True, text=True)
    if 'QA Bot         : RUNNING' not in status.stdout:
        print("QA Bot not running! Starting...")
        subprocess.Popen(['./scripts/start_qa.sh'])
        time.sleep(5)

def send_message(page, text, screenshot_name=None):
    print(f"Sending: {text}")
    page.fill('#editable-message-text', text)
    page.wait_for_timeout(500)
    page.click('button.send, .btn-send, [title="Send Message"], [aria-label="Send Message"], .icon-send', force=True)
    page.keyboard.press('Enter')
    page.wait_for_timeout(4000)  # Wait for reply
    if screenshot_name:
        page.screenshot(path=f'testing/playwright/screenshots/5C3A/{screenshot_name}.png')

def run_smoke_tests():
    ensure_qa_bot()
    
    os.makedirs('testing/playwright/screenshots/5C3A', exist_ok=True)
    os.makedirs('testing/playwright/traces/5C3A', exist_ok=True)
    
    with sync_playwright() as p:
        profile_path = os.path.abspath('testing/playwright/profile')
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=profile_path,
            headless=False,
            record_video_dir='testing/playwright/traces/5C3A',
            viewport={'width': 1280, 'height': 720}
        )
        ctx.tracing.start(screenshots=True, snapshots=True, sources=True)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        
        print("Navigating to Telegram Web...")
        page.goto('https://web.telegram.org/a/')
        page.wait_for_selector('#telegram-search-input', timeout=20000)
        page.wait_for_timeout(3000)
        
        print("Opening @Baka_qa_bot...")
        page.click('#telegram-search-input')
        page.keyboard.type('@Baka_qa_bot', delay=50)
        page.wait_for_timeout(3000)
        
        peer_locator = page.locator('.LeftSearch .ListItem').filter(has=page.locator('[data-peer-id]')).first
        peer_locator.wait_for(state='visible', timeout=15000)
        peer_locator.click()
        
        page.wait_for_selector('#editable-message-text', timeout=15000)
        page.wait_for_timeout(2000)
        
        # Admin Claim
        send_message(page, '/claimadmin', 'claimadmin')
        
        # 1. Core Commands
        send_message(page, '/start', 'start')
        send_message(page, '/help', 'help')
        send_message(page, '/commands', 'commands')
        send_message(page, '/today', 'today')
        send_message(page, '/tasks', 'tasks')
        send_message(page, '/version', 'version')
        
        # 2. Natural Language Task Tests
        send_message(page, 'Remind me to buy milk tomorrow', 'task_en')
        send_message(page, 'Kal subah 8 baje gym yaad dila dena', 'task_hi')
        send_message(page, 'Bhai next Friday assignment submit karna hai', 'task_mix')
        
        # 3. Goal & Habit Live Tests
        send_message(page, 'New goal: learn python by next month', 'goal_create')
        send_message(page, 'I studied python for 2 hours today', 'goal_update')
        send_message(page, 'Finished python', 'goal_complete')
        
        send_message(page, 'New habit: exercise daily', 'habit_create')
        send_message(page, 'I exercised today', 'habit_complete')
        send_message(page, 'What is my exercise streak?', 'habit_streak')
        send_message(page, 'Skip exercise today', 'habit_skip')
        send_message(page, 'Pause exercise today', 'habit_pause')
        send_message(page, 'Resume exercise today', 'habit_resume')
        
        # 4. Callback Regression Validation
        send_message(page, '/start', 'dashboard_fresh')
        buttons = page.locator('.reply-markup-button')
        if buttons.count() > 0:
            print("Clicking a callback button (e.g. Dashboard refresh)...")
            buttons.first.click()
            page.wait_for_timeout(3000)
            page.screenshot(path='testing/playwright/screenshots/5C3A/callback_click.png')
            
        print("Smoke tests completed.")
        ctx.tracing.stop(path='testing/playwright/traces/5C3A/trace.zip')
        ctx.close()

if __name__ == '__main__':
    run_smoke_tests()
