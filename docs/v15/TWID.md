# TWID — Telegram Workspace Integration Design (v15.0)

*Design only.*

## 1. Principle

**SQLite is the source of truth. Telegram is a synchronized projection
and a human-readable archive.** The user creates a private **supergroup
with Topics enabled** and adds BAKA as administrator; BAKA creates and
manages one Topic per Workspace (and per top-level category), and posts
each important update there so the group becomes a readable journal.

The architecture **must tolerate Telegram being unavailable** — nothing
in the workspace engine blocks on Telegram. This is the
`notification_service` reliability model (v13.0: rate-limit buckets +
retry) applied to workspace sync.

## 2. Topic organization

```
Supergroup: "BAKA Workspace"  (Topics enabled, bot = admin)
├── Topic: Projects      (category)
│     └── posts: one thread per project workspace's journal
├── Topic: Research
├── Topic: Books
├── Topic: Games
├── Topic: Journal       (daily/weekly/monthly rollups — KTD)
├── Topic: Ideas
└── Topic: Knowledge
```

Two mapping options, decided per deployment scale:
- **A — Topic per Workspace** (default for active workspaces): the
  workspace's timeline is its thread. `workspaces.telegram_topic_id`
  stores the mapping.
- **B — Topic per Category, post per Workspace**: for many small
  workspaces, category Topics (Projects/Books/…) hold one anchored
  message per workspace, updated in place. Chosen when a user exceeds a
  configurable workspace count (Telegram caps topics per group).

Category→Topic and Workspace→Topic maps live in SQLite
(`workspaces.telegram_topic_id` + a small `telegram_topics` table:
`id, user_id, kind (category|workspace), ref_id, topic_id`).

## 3. Synchronization (outbox pattern)

Workspace writes **never call Telegram inline.** They append to a
durable **outbox**; a background worker drains it. This decouples
correctness (SQLite) from delivery (Telegram).

```sql
sync_outbox (
  id INTEGER PK, user_id INTEGER,
  workspace_id INTEGER, timeline_event_id INTEGER,   -- what to post
  topic_id INTEGER,                                   -- resolved target (nullable until known)
  payload TEXT,                                       -- rendered message (HTML)
  status TEXT DEFAULT 'pending',                      -- pending | sent | failed
  attempts INTEGER DEFAULT 0,
  last_error TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  sent_at TEXT
)
```

Flow: **write → timeline event → enqueue outbox row → worker posts →
mark sent (store Telegram message_id) → mark event `synced_at`.**

- The worker runs on the existing `job_queue` (like `check_reminders`),
  every N seconds, draining `pending` rows oldest-first.
- **Idempotency:** each outbox row maps to exactly one timeline event id;
  re-running never double-posts (a `sent` row is skipped). If a post
  succeeds but the "mark sent" write fails, the stored Telegram
  `message_id` + event id let the next pass detect and skip the dup.
- **Topic creation is lazy & cached:** first post to a workspace creates
  its Topic (if missing), stores `telegram_topic_id`, then posts.

## 4. Recovery & offline behaviour

- **Telegram down:** outbox rows stay `pending`; the engine keeps working
  on SQLite. When Telegram returns, the worker drains the backlog in
  order. No data loss, no blocking.
- **Bot restart:** the outbox is persistent (SQLite) → the worker resumes
  from `pending`. Conversation/session state is in-memory (unchanged),
  but sync state is durable.
- **Bounded backlog:** if `pending` grows beyond a threshold (extended
  outage), the worker coalesces per-workspace updates (post a single
  "catch-up" summary rather than N stale events) to respect rate limits.
- **Reconciliation:** a periodic check compares `timeline_events` with no
  `synced_at` against the outbox to re-enqueue anything dropped.

## 5. Rate limiting

Reuse `notification_service.TelegramSender`'s per-chat + overall
rate-limit buckets (already handles `RetryAfter`/`TimedOut`/
`NetworkError` with backoff). Workspace sync is just another producer
into that limiter — no new limiter. The worker paces itself to the
limiter; bursts (bulk migration backfill) are drained slowly, not
dropped.

## 6. Permissions & safety

- **Bot as admin, minimum rights:** manage topics + post messages. It
  does not need delete-message or ban rights.
- **Group membership = access:** only the owner's private supergroup is
  synced; the bot ignores messages from groups it wasn't configured for.
  Admin-only Developer Center rules (v14.22) extend here — workspace
  management commands are owner-gated.
- **No secrets in Topics:** the log sanitizer (v14.12) already scrubs
  tokens/keys; workspace posts are user content (task titles, notes) —
  rendered via `fmt.py` escaping, same as every other message.
- **Read-back is not trusted as source of truth:** even if a user edits a
  journal message in Telegram, SQLite remains authoritative; Telegram
  edits are not parsed back (one-way projection in v15; two-way is a
  future item, explicitly out of scope).

## 7. What this preserves

- Zero change to the current single-DM interface when the flag is OFF or
  no workspace group is configured — the supergroup is opt-in.
- `notification_service`, `job_queue`, and reminder delivery are reused,
  not modified; workspace sync is an additional job + producer.
