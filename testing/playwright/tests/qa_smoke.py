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
        page.screenshot(path=f'testing/playwright/screenshots/5C3/{screenshot_name}.png')

def run_smoke_tests():
    ensure_qa_bot()
    
    os.makedirs('testing/playwright/screenshots/5C3', exist_ok=True)
    os.makedirs('testing/playwright/traces/5C3', exist_ok=True)
    reports_dir = os.path.abspath('testing/playwright/reports/html')
    os.makedirs(reports_dir, exist_ok=True)
    
    with sync_playwright() as p:
        profile_path = os.path.abspath('testing/playwright/profile')
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=profile_path,
            headless=False,
            record_video_dir='testing/playwright/traces/5C3',
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
        
        # 5C.3A Core Commands & 5C.3G Admin (Denied)
        send_message(page, '/start', 'start')
        send_message(page, '/selftest', 'admin_denied')
        send_message(page, '/claimadmin', 'claimadmin')
        send_message(page, '/help', 'help')
        send_message(page, '/commands', 'commands')
        send_message(page, '/today', 'today')
        send_message(page, '/tasks', 'tasks')
        
        # 5C.3B Tasks
        send_message(page, 'Remind me to buy milk tomorrow', 'task_create')
        send_message(page, 'I bought the milk', 'task_complete')
        send_message(page, 'Delete the buy milk task', 'task_delete')
        send_message(page, 'Remind me to drink water every day', 'task_recurring')
        
        # 5C.3C Goals
        send_message(page, 'New goal: learn python by next month', 'goal_create')
        send_message(page, 'I studied python for 2 hours today', 'goal_update')
        
        # 5C.3D Habits
        send_message(page, 'New habit: exercise daily', 'habit_create')
        send_message(page, 'I exercised today', 'habit_complete')
        send_message(page, 'Skip exercise today', 'habit_skip')
        send_message(page, 'What is my exercise streak?', 'habit_streak')
        
        # 5C.3E Dashboard
        send_message(page, '/start', 'dashboard_fresh')
        # Click a callback button if present
        buttons = page.locator('.reply-markup-button')
        if buttons.count() > 0:
            print("Clicking a callback button...")
            buttons.first.click()
            page.wait_for_timeout(3000)
            page.screenshot(path='testing/playwright/screenshots/5C3/dashboard_click.png')
            
        # 5C.3F Workspace OS
        send_message(page, 'Create a new workspace for Project X', 'workspace_create')
        send_message(page, 'Add milestone Phase 1 to Project X', 'workspace_milestone')
        send_message(page, 'Show Project X timeline', 'workspace_timeline')
        
        # 5C.3G Admin (Granted)
        send_message(page, '/version', 'admin_version')
        send_message(page, '/selftest', 'admin_selftest')
        send_message(page, '/debug', 'admin_debug')
        
        print("Smoke tests completed.")
        ctx.tracing.stop(path='testing/playwright/traces/5C3/trace.zip')
        ctx.close()

if __name__ == '__main__':
    run_smoke_tests()
