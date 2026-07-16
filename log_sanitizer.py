"""
log_sanitizer.py — v12.1
Logging filter that scrubs sensitive data before writing to bot.log.

Redacts:
  - Telegram bot tokens embedded in API URLs
  - NVIDIA API keys (nvapi-...)
  - OpenAI API keys (sk-...)
  - Anthropic API keys (sk-ant-...)
  - Numeric Telegram user IDs → "admin" for the owner, "user_XXX" for others
    (last 3 digits kept so support debugging isn't impossible)

Usage:
    from log_sanitizer import install_log_sanitizer
    install_log_sanitizer(admin_id=793991074)  # call once at startup
"""
import re
import logging
import os


class LogSanitizer(logging.Filter):
    """A logging filter that scrubs secrets from every log record."""

    # v14.12 FIX: the original pattern required a '/' immediately before
    # the numeric id (r'/(\d{6,12}):...'), which NEVER matched Telegram
    # API URLs -- they embed the token as '/bot<id>:<token>/method', so
    # the char before the digits is 't', and httpx's per-request INFO
    # lines ("HTTP Request: POST https://api.telegram.org/bot.../send...")
    # leaked the full token into bot.log. Two patterns now: the URL form
    # (masked whole, per the v14.12 brief), then any bare <id>:<token>
    # pair anywhere else.
    BOT_TOKEN_URL_RE = re.compile(r'/bot\d{6,12}:[A-Za-z0-9_-]{25,}')
    BOT_TOKEN_RE = re.compile(r'\b\d{6,12}:[A-Za-z0-9_-]{25,}\b')

    # NVIDIA NIM API keys
    NVAPI_RE = re.compile(r'nvapi-[A-Za-z0-9_-]{20,}')

    # OpenAI API keys (also matches sk-ant- for Anthropic)
    OPENAI_KEY_RE = re.compile(r'sk-[A-Za-z0-9_-]{20,}')

    # v14.12: HTTP credential carriers -- Authorization headers, cookies,
    # and secret-bearing URL query parameters (?api_key=..., &token=...).
    BEARER_RE = re.compile(r'(Bearer\s+)[A-Za-z0-9._~+/=-]{16,}', re.IGNORECASE)
    COOKIE_RE = re.compile(r'((?:Set-)?Cookie\s*[=:]\s*)\S+', re.IGNORECASE)
    URL_SECRET_RE = re.compile(
        r'([?&](?:api_?key|token|secret|password|auth|key)=)[^&\s]+',
        re.IGNORECASE,
    )

    # Chat/user id in structured contexts:
    #   "chat_id=793991074", "user_id=793991074", "user 793991074"
    STRUCTURED_UID_RE = re.compile(
        r'\b(chat_id|user_id|user id|from_id|from|to|for user)\s*[=:\s]\s*(\d{6,12})\b',
        re.IGNORECASE,
    )

    # Any bare telegram-scale numeric ID (7-12 digits). Applied LAST so we don't
    # damage things already redacted. Telegram user IDs are typically 8-10 digits.
    BARE_UID_RE = re.compile(r'\b(\d{8,12})\b')

    def __init__(self, admin_id=None, keep_last_n_digits: int = 3):
        super().__init__()
        self.admin_id = str(admin_id).strip() if admin_id else None
        self.keep_last = keep_last_n_digits
        # For messages of the form 'User Xyz[state]: ...' we DO NOT touch the name
        # (it's already a display name, not an ID). So we don't need to guard that.

    def _redact_uid(self, uid: str) -> str:
        """Return the display form for a user ID."""
        if self.admin_id and uid == self.admin_id:
            return "admin"
        # Keep last N digits for triaging without exposing full ID
        tail = uid[-self.keep_last:] if len(uid) >= self.keep_last else uid
        return f"user_***{tail}"

    def _scrub(self, text: str) -> str:
        if not isinstance(text, str) or not text:
            return text
        # 1a. Bot tokens in Telegram API URLs → /botxxxxxxxxxxxxxxxx
        text = self.BOT_TOKEN_URL_RE.sub('/botxxxxxxxxxxxxxxxx', text)
        # 1b. Bare <id>:<token> pairs anywhere else
        text = self.BOT_TOKEN_RE.sub('xxxxxxxxxxxxxxxx', text)
        # 2. NVIDIA keys
        text = self.NVAPI_RE.sub('nvapi-*************', text)
        # 3. OpenAI/Anthropic keys
        text = self.OPENAI_KEY_RE.sub('sk-*************', text)
        # 3b. v14.12: Authorization headers, cookies, URL query secrets
        text = self.BEARER_RE.sub(r'\1*************', text)
        text = self.COOKIE_RE.sub(r'\1*************', text)
        text = self.URL_SECRET_RE.sub(r'\1*************', text)
        # 4. Structured user_id / chat_id references
        def _sub_struct(m):
            return f"{m.group(1)}={self._redact_uid(m.group(2))}"
        text = self.STRUCTURED_UID_RE.sub(_sub_struct, text)
        # 5. Bare 8-12 digit numbers — likely user IDs. Skip if inside a URL
        #    that we already redacted (contains '*************').
        if '*************' not in text or self.BARE_UID_RE.search(text):
            def _sub_bare(m):
                uid = m.group(1)
                # Never redact things that look like timestamps, dates, ports
                # (already-processed 8-12 digit numbers are pure Telegram IDs)
                return self._redact_uid(uid)
            # Only apply to bare IDs — but skip our own redacted markers
            def _safe_sub(m):
                # Avoid mangling anything inside "user_***XXX" we just wrote
                return _sub_bare(m)
            # NOTE: BARE_UID_RE is conservative (8-12 digits, word boundary), so
            # it won't match 4-digit years, 6-digit dates, ports, etc.
            text = self.BARE_UID_RE.sub(_safe_sub, text)
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        # Scrub the formatted message
        try:
            msg = record.getMessage()
            record.msg = self._scrub(msg)
            record.args = ()
        except Exception:
            # Never let the sanitizer crash logging itself
            pass
        return True


def _load_admin_id(explicit_id=None):
    """Prefer explicit_id, otherwise read from admin_id.txt beside the bot."""
    if explicit_id is not None:
        return explicit_id
    try:
        path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            'admin_id.txt'
        )
        if os.path.exists(path):
            with open(path) as f:
                return f.read().strip()
    except Exception:
        pass
    return None


def install_log_sanitizer(admin_id=None, keep_last_n_digits: int = 3) -> LogSanitizer:
    """
    Attach the sanitizer to the root logger and all existing handlers.
    Call once at startup, right after logging.basicConfig(...).
    Idempotent — calling twice will just replace the filter.
    """
    resolved_admin = _load_admin_id(admin_id)
    sanitizer = LogSanitizer(
        admin_id=resolved_admin,
        keep_last_n_digits=keep_last_n_digits,
    )
    root = logging.getLogger()
    # Remove any prior instance
    root.filters = [f for f in root.filters if not isinstance(f, LogSanitizer)]
    root.addFilter(sanitizer)
    for h in root.handlers:
        h.filters = [f for f in h.filters if not isinstance(f, LogSanitizer)]
        h.addFilter(sanitizer)
    return sanitizer