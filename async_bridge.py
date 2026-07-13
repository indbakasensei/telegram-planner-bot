"""
async_bridge.py — the single seam between BAKA's async Telegram handlers
and baka_brain.py's synchronous AI/media calls.

Why this exists (see ENGINEERING_AUDIT.md finding C1/I1, CRITICAL):
baka_brain.py uses a synchronous OpenAI client and a synchronous httpx
client for image/video generation. Called directly from an `async def`
handler, a slow AI call or a multi-minute video-generation request blocks
the ENTIRE bot's event loop — every other user's messages, every button
tap, and every scheduled job stall until it returns.

The fix is not to scatter `await asyncio.to_thread(...)` across every call
site with bespoke wrapping — that duplicates the same boilerplate at each
of baka_brain.py's ~15 entry points and leaves no single place to evolve
the strategy later. Instead, every caller routes through `run_blocking()`
here. baka_brain.py itself is untouched: its internal call graph (e.g.
generate_video() calling generate_image() synchronously) keeps working
correctly, because once a call enters a worker thread via run_blocking(),
everything it calls internally still runs in that same thread, still
synchronously — no internal `await` needed.

Migration path: when baka_brain.py is eventually migrated to a native
async client (AsyncOpenAI, httpx.AsyncClient), call sites using
run_blocking() do not need to change one at a time — this module becomes
the one place to update (e.g. have run_blocking() detect an awaitable
result and return it directly instead of offloading). Nothing about that
future migration is implemented here; this sprint only adds the seam.

Scope note: database.py calls are deliberately NOT routed through this
helper. Benchmarked directly against the live planner.db, a representative
database.py call (connect + query + close) averages 0.3-0.4ms — orders of
magnitude below anything a user or the scheduler would notice, unlike the
AI/media calls this module exists for. See ENGINEERING_AUDIT.md for the
full reasoning.
"""
import asyncio
from typing import Any, Callable, TypeVar

T = TypeVar("T")


async def run_blocking(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Run a synchronous, potentially slow callable off the event loop.

    Usage: `result = await run_blocking(generate_image, prompt, user_id=uid)`
    instead of `result = generate_image(prompt, user_id=uid)`.
    """
    return await asyncio.to_thread(fn, *args, **kwargs)
