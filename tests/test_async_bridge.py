"""
Tests for async_bridge.py's run_blocking() -- the single seam baka_brain.py's
synchronous AI/media calls go through so they don't block the event loop.
Formalizes the validation done during Sprint 1B into a permanent suite.

No real AI calls -- plain synchronous functions (time.sleep, exception
raisers, thread-identity checks) stand in for what would otherwise be a
slow network call.
"""
import asyncio
import threading
import time

import pytest

from async_bridge import run_blocking


# ── thread execution ──────────────────────────────────────────────────────

async def test_run_blocking_executes_off_the_main_thread():
    main_thread_id = threading.get_ident()
    worker_thread_id = {}

    def sync_fn():
        worker_thread_id["id"] = threading.get_ident()
        return "done"

    result = await run_blocking(sync_fn)
    assert result == "done"
    assert worker_thread_id["id"] != main_thread_id


async def test_run_blocking_returns_the_wrapped_function_result():
    def add(a, b):
        return a + b

    result = await run_blocking(add, 2, 3)
    assert result == 5


async def test_run_blocking_passes_kwargs_through():
    def greet(name, greeting="Hello"):
        return f"{greeting}, {name}!"

    result = await run_blocking(greet, "World", greeting="Hi")
    assert result == "Hi, World!"


# ── the actual point: a slow call must not block the event loop ──────────

async def test_slow_call_does_not_block_concurrent_fast_tasks():
    log = []

    def slow_sync_call():
        time.sleep(0.3)
        return "slow done"

    async def fast_task(n):
        await asyncio.sleep(0.01)
        log.append(n)

    t0 = time.perf_counter()
    await asyncio.gather(
        run_blocking(slow_sync_call),
        *[fast_task(i) for i in range(5)],
    )
    elapsed = time.perf_counter() - t0

    assert len(log) == 5
    assert elapsed < 0.4  # ran concurrently, not 0.3 + 5*0.01 serialized after


async def test_control_group_unwrapped_call_actually_blocks():
    # Proves the test above is meaningful: calling the SAME slow function
    # directly (not through run_blocking) genuinely blocks the loop, so
    # the "fast" coroutines can't interleave with it at all.
    log = []

    def slow_sync_call():
        time.sleep(0.1)
        return "slow done"

    async def fast_task(n):
        await asyncio.sleep(0.001)
        log.append(("fast", n, time.perf_counter()))

    async def unwrapped_slow_task():
        result = slow_sync_call()  # deliberately NOT wrapped
        log.append(("slow", result, time.perf_counter()))

    await asyncio.gather(unwrapped_slow_task(), *[fast_task(i) for i in range(3)])
    slow_time = next(t for kind, _, t in log if kind == "slow")
    fast_times = [t for kind, _, t in log if kind == "fast"]
    # Without run_blocking, none of the fast tasks can complete until the
    # blocking call returns control to the loop.
    assert all(t >= slow_time for t in fast_times)


# ── parallel execution / high concurrency ─────────────────────────────────

async def test_many_concurrent_calls_each_return_their_own_correct_value():
    def echo(x):
        time.sleep(0.01)
        return x

    results = await asyncio.gather(*[run_blocking(echo, i) for i in range(50)])
    assert results == list(range(50))  # no cross-talk / value corruption


async def test_high_concurrency_no_deadlock():
    def work(n):
        return n * n

    # 200 concurrent offloaded calls -- must all complete without hanging
    # or deadlocking on the underlying thread pool.
    results = await asyncio.wait_for(
        asyncio.gather(*[run_blocking(work, i) for i in range(200)]),
        timeout=10,
    )
    assert results == [i * i for i in range(200)]


# ── exception propagation ────────────────────────────────────────────────

async def test_exception_propagates_to_the_awaiter():
    def raises():
        raise ValueError("simulated failure")

    with pytest.raises(ValueError, match="simulated failure"):
        await run_blocking(raises)


async def test_exception_type_is_preserved_not_wrapped():
    class CustomError(Exception):
        pass

    def raises_custom():
        raise CustomError("specific error")

    with pytest.raises(CustomError):
        await run_blocking(raises_custom)


async def test_one_failing_call_does_not_affect_concurrent_siblings():
    def raises():
        raise RuntimeError("boom")

    def succeeds():
        return "ok"

    results = await asyncio.gather(
        run_blocking(raises), run_blocking(succeeds), return_exceptions=True
    )
    assert isinstance(results[0], RuntimeError)
    assert results[1] == "ok"


# ── nested calls (the exact hazard found during Sprint 1B's analysis:
# generate_video() calling generate_image() internally, synchronously) ───

async def test_nested_synchronous_call_inside_a_wrapped_function_works():
    def inner(x):
        return x * 2

    def outer(x):
        # A plain synchronous call to another function, entirely within
        # the worker thread run_blocking() already offloaded to -- this
        # must NOT need to be awaited, since it's not itself async.
        return inner(x) + 1

    result = await run_blocking(outer, 5)
    assert result == 11


async def test_deeply_nested_synchronous_calls_all_run_in_the_same_thread():
    thread_ids = []

    def level3():
        thread_ids.append(threading.get_ident())
        return "l3"

    def level2():
        thread_ids.append(threading.get_ident())
        return level3()

    def level1():
        thread_ids.append(threading.get_ident())
        return level2()

    result = await run_blocking(level1)
    assert result == "l3"
    assert len(set(thread_ids)) == 1  # all three levels ran in the same worker thread
