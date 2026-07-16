"""
Tests for fmt.py -- first covered in v14.12, when the rich-UI pass
added the remaining Telegram HTML entities (spoiler, blockquotes,
language-tagged code blocks). Pins the one property everything
user-facing depends on: user content is ALWAYS escaped (the v7.1
Markdown-corruption lesson), and pre-formatted content is only embedded
unescaped when the caller explicitly says so.
"""
from fmt import (
    b, blockquote, code, code_block, esc, expandable_blockquote, i, pre,
    spoiler, u,
)

HOSTILE = 'Read <b>ooks & "sleep"'
HOSTILE_ESCAPED = 'Read &lt;b&gt;ooks &amp; "sleep"'


def test_esc_escapes_exactly_the_three_html_specials():
    assert esc(HOSTILE) == HOSTILE_ESCAPED
    assert esc(None) == ""
    assert esc(42) == "42"


def test_wrappers_escape_content():
    assert b(HOSTILE) == f"<b>{HOSTILE_ESCAPED}</b>"
    assert i(HOSTILE) == f"<i>{HOSTILE_ESCAPED}</i>"
    assert u(HOSTILE) == f"<u>{HOSTILE_ESCAPED}</u>"
    assert code(HOSTILE) == f"<code>{HOSTILE_ESCAPED}</code>"
    assert pre(HOSTILE) == f"<pre>{HOSTILE_ESCAPED}</pre>"
    assert spoiler(HOSTILE) == f"<tg-spoiler>{HOSTILE_ESCAPED}</tg-spoiler>"


def test_code_block_plain_and_language_tagged():
    assert code_block("x = 1") == "<pre><code>x = 1</code></pre>"
    assert code_block("x = 1", lang="python") == (
        '<pre><code class="language-python">x = 1</code></pre>')
    assert "&lt;script&gt;" in code_block("<script>", lang="html")


def test_blockquotes_escape_by_default():
    assert blockquote(HOSTILE) == f"<blockquote>{HOSTILE_ESCAPED}</blockquote>"
    assert expandable_blockquote(HOSTILE) == (
        f"<blockquote expandable>{HOSTILE_ESCAPED}</blockquote>")


def test_blockquotes_can_embed_prebuilt_html():
    inner = f"{b('Tasks')}\n{code('list')}"
    assert blockquote(inner, escape=False) == f"<blockquote>{inner}</blockquote>"
    assert expandable_blockquote(inner, escape=False) == (
        f"<blockquote expandable>{inner}</blockquote>")
