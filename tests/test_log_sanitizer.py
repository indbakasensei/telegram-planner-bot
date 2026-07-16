"""
Tests for log_sanitizer.py -- first covered in v14.12, when the token
leak was found and fixed: the original BOT_TOKEN_RE required a '/'
immediately before the numeric id, which never matched real Telegram
API URLs ('/bot<id>:<token>/method' puts a 't' there), so httpx's
per-request INFO lines leaked the full bot token into bot.log. These
tests pin the fix against the EXACT line format httpx logs, plus every
other masking rule.
"""
import logging

import pytest

from log_sanitizer import LogSanitizer, install_log_sanitizer

TOKEN = "7123456789:AAHfake-token_ABCDEFGHIJKLMNOPQRSTU"


@pytest.fixture
def scrub():
    return LogSanitizer(admin_id=793991074)._scrub


def test_masks_token_in_httpx_request_line(scrub):
    # The exact format httpx logs for every Telegram API call -- the
    # line that was leaking before v14.12.
    line = (f'HTTP Request: POST https://api.telegram.org/bot{TOKEN}/sendMessage '
            f'"HTTP/1.1 200 OK"')
    out = scrub(line)
    assert TOKEN not in out
    assert "https://api.telegram.org/botxxxxxxxxxxxxxxxx/sendMessage" in out


def test_masks_bare_token_outside_urls(scrub):
    out = scrub(f"starting with token {TOKEN} configured")
    assert TOKEN not in out
    assert "xxxxxxxxxxxxxxxx" in out


def test_masks_getupdates_polling_line(scrub):
    line = f"HTTP Request: POST https://api.telegram.org/bot{TOKEN}/getUpdates"
    out = scrub(line)
    assert TOKEN not in out


def test_masks_nvidia_and_openai_keys(scrub):
    out = scrub("key=nvapi-AbCdEfGhIjKlMnOpQrStUvWx and sk-abcdefghijklmnopqrstuvwx")
    assert "nvapi-*************" in out and "sk-*************" in out
    assert "AbCdEfGh" not in out


def test_masks_bearer_and_cookie_headers(scrub):
    out = scrub("Authorization: Bearer abc123def456ghi789jkl and Cookie: session=deadbeef")
    assert "Bearer *************" in out
    assert "abc123def456" not in out
    assert "session=deadbeef" not in out


def test_masks_url_query_secrets(scrub):
    out = scrub("GET https://x.example/v1?api_key=supersecret123&user=7")
    assert "supersecret123" not in out
    assert "api_key=*************" in out


def test_redacts_user_ids_admin_vs_other(scrub):
    out = scrub("chat_id=793991074 user_id=555000111")
    assert "admin" in out
    assert "user_***111" in out
    assert "555000111" not in out


def test_never_crashes_on_non_string():
    sanitizer = LogSanitizer()
    assert sanitizer._scrub(None) is None
    assert sanitizer._scrub("") == ""


def test_filter_scrubs_log_records():
    sanitizer = LogSanitizer()
    record = logging.LogRecord(
        "test", logging.INFO, __file__, 1,
        f"POST https://api.telegram.org/bot{TOKEN}/sendMessage", (), None)
    assert sanitizer.filter(record) is True       # never suppresses records
    assert TOKEN not in record.getMessage()


def test_install_attaches_to_root_and_handlers_idempotently():
    root = logging.getLogger()
    before_handlers = list(root.handlers)
    try:
        install_log_sanitizer(admin_id=1)
        install_log_sanitizer(admin_id=1)          # idempotent
        assert sum(isinstance(f, LogSanitizer) for f in root.filters) == 1
        for h in root.handlers:
            assert sum(isinstance(f, LogSanitizer) for f in h.filters) == 1
    finally:
        root.filters = [f for f in root.filters if not isinstance(f, LogSanitizer)]
        for h in before_handlers:
            h.filters = [f for f in h.filters if not isinstance(f, LogSanitizer)]
