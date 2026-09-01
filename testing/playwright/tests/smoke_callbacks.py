import os
import time
import subprocess
from playwright.sync_api import sync_playwright

def send_message_and_click(page, text, button_text_substring, screenshot_name=None):
    print(f"Sending: {text} to click '{button_text_substring}'")
    page.fill('#editable-message-text', text)
    page.wait_for_timeout(500)
    page.click('button.send, .btn-send, [title="Send Message"], [aria-label="Send Message"], .icon-send', force=True)
    page.keyboard.press('Enter')
    page.wait_for_timeout(4000)
    
    button = page.get_by_text(button_text_substring).last
    try:
        button.wait_for(state='visible', timeout=5000)
        button.click()
        print(f"PASS: Clicked {button_text_substring}")
        page.wait_for_timeout(3000)
        if screenshot_name:
            page.screenshot(path=f'testing/playwright/screenshots/5C3A/{screenshot_name}.png')
        return True
    except Exception as e:
        print(f"FAIL: Button '{button_text_substring}' not found! {e}")
        return False

def run_callback_tests():
    os.makedirs('testing/playwright/screenshots/5C3A', exist_ok=True)
    
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
        
        print("Opening @Baka_qa_bot...")
        page.click('#telegram-search-input')
        page.keyboard.type('@Baka_qa_bot', delay=50)
        page.wait_for_timeout(3000)
        
        peer_locator = page.locator('.LeftSearch .ListItem').filter(has=page.locator('[data-peer-id]')).first
        peer_locator.wait_for(state='visible', timeout=15000)
        peer_locator.click()
        page.wait_for_selector('#editable-message-text', timeout=15000)
        page.wait_for_timeout(2000)
        
        results = {}
        
        # We need to make sure the dev admin is claimed!
        send_message_and_click(page, '/claimadmin', 'Claim') # Dummy
        
        # dev:* - /debug
        results['dev:*'] = send_message_and_click(page, '/debug', 'Self Test', 'callback_dev')
        
        # dash:* - /dashboard
        results['dash:*'] = send_message_and_click(page, '/dashboard', 'Refresh', 'callback_dash')
        
        # cmd:* - /start
        results['cmd:*'] = send_message_and_click(page, '/start', 'Admin', 'callback_cmd')
        
        # habit:* - /habits (assumes habit exists from previous run)
        results['habit:*'] = send_message_and_click(page, '/habits', 'Complete', 'callback_habit')
        
        # done:* - /today
        results['done:*'] = send_message_and_click(page, '/today', 'Done', 'callback_done')
        
        # proj:*
        results['proj:*'] = send_message_and_click(page, '/projects', 'Project', 'callback_proj')
        
        # ctl:* - /debug -> Self Test triggers a ctl: ?
        results['ctl:*'] = send_message_and_click(page, '/debug', 'Debug OFF', 'callback_ctl')
        
        print("--- CALLBACK TEST RESULTS ---")
        for k, v in results.items():
            print(f"{k}: {'PASS' if v else 'FAIL'}")
            
        ctx.close()

if __name__ == '__main__':
    run_callback_tests()
