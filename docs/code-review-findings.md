# Code Review Findings — MCP Brain src/

Comprehensive review by 3 parallel agents (Reuse, Quality, Efficiency) across all 11 source files.

## Critical Bugs

### BUG-1: `get_memory_stats` timestamps are broken (CRITICAL)
**File:** `src/db/memories.py:196-223`
The `MIN(created_at)` and `MAX(created_at)` operate on a subquery that doesn't include `created_at` — they will return NULL or wrong values. The subquery only has `memory_type` and `type_count`.

**Fix:** Rewrite to include timestamps in the subquery or use a single-pass query with conditional aggregation.

### BUG-2: `profiles.py` has no UUID validation (HIGH)
**File:** `src/db/profiles.py:20,29,39`
All three functions call `uuid.UUID(user_id)` with no try/except. Invalid UUID strings raise unhandled `ValueError` → 500 errors. Unlike `memories.py` and `banks.py` which have guards.

**Fix:** Add try/except or use shared UUID parser (see R-1).

## Code Reuse (10 findings)

### R-1: UUID parsing duplicated 13 times with inconsistent fallbacks (HIGH)
**Files:** All db/ modules
Every DB function has identical `try: uuid.UUID(user_id) except ValueError: return <fallback>` but with different fallbacks ([], None, 0, False, dict). Extract `parse_uuid()` utility.

### R-2: Error response construction duplicated 10+ times (HIGH)
**File:** `src/server.py`, `src/tools/memory_tools.py`
`{"status": "error", "error": "...", "message": "..."}` is hand-built everywhere. Extract `error_response(code, message)` helper.

### R-3: Memory serialization duplicated between search and list (MEDIUM)
**File:** `src/tools/memory_tools.py:122-132 vs 151-161`
Nearly identical dict comprehensions. Extract `_serialize_memory()`.

### R-4: Memory limit message duplicated identically (LOW)
**File:** `src/tools/memory_tools.py:39-43 and 82-86`

### R-5: `memory_type` validation duplicated between create and list (LOW)
**File:** `src/server.py:155-163 and 275-283`

### R-6: Two DB queries where one suffices for subscription + count (MEDIUM)
**File:** `src/tools/memory_tools.py:31-36`
`is_subscription_active()` and `get_memory_count()` are separate roundtrips to the same table.

### R-7: `list_memories` query has full duplication for optional filter (LOW)
**File:** `src/db/memories.py:141-169`
Two near-identical SQL queries differing by one WHERE clause.

### R-8: `np.array(embedding, dtype=np.float32)` duplicated (LOW)
**File:** `src/db/memories.py:38 and 84`

### R-9: `source` default `"mcp"` hardcoded in 3 places (LOW)
**Files:** `src/server.py:123`, `src/tools/memory_tools.py:22`, `src/db/memories.py:22`

### R-10: No bank_tools.py — server.py reaches directly into banks DB (MEDIUM)
**File:** `src/server.py:71-100, 336-350`
`_resolve_auth` and `list_banks` bypass the tools layer.

## Code Quality (7 findings)

### Q-1: `datetime.utcnow()` deprecated since Python 3.12 (MEDIUM)
**File:** `src/metadata.py:46`

### Q-2: Stringly-typed memory types and sources (MEDIUM)
**Files:** `src/config.py:51-60`, `src/metadata.py:59-71`
Should be `StrEnum` for type safety.

### Q-3: Error codes are scattered raw strings (LOW)
**Files:** `src/server.py`, `src/tools/memory_tools.py`

### Q-4: `create_bank` exception handler leaks partial DB errors (HIGH)
**File:** `src/db/banks.py:132-136`
Catches generic `Exception`, checks for "unique" in error message string. Should catch `asyncpg.UniqueViolationError` specifically.

### Q-5: `SUPABASE_SERVICE_ROLE_KEY` loaded but unused (MEDIUM)
**File:** `src/config.py:15`
Sits in process memory unnecessarily.

### Q-6: Connection pool never closed on shutdown (MEDIUM)
**File:** `src/main.py` — no lifespan handler. `close_pool()` exists but is never called.

### Q-7: `create_memory` has 9 parameters (LOW)
**File:** `src/db/memories.py:14-24` — consider a `MemoryInput` dataclass.

## Efficiency (12 findings)

### E-1: Two DB roundtrips for subscription check + count (MEDIUM)
**File:** `src/tools/memory_tools.py:31-36`
Combine into single query.

### E-2: `_resolve_auth` bank resolution hits DB on every tool call (HIGH)
**File:** `src/server.py:71-100`
No caching. Same default bank queried 10+ times per conversation. Add TTL cache.

### E-3: `list_banks` resolves bank_id then throws it away (MEDIUM)
**File:** `src/server.py:326-350`
Wasted DB query. Extract `_resolve_user()` for tools that don't need bank.

### E-4: No batch embedding support (HIGH for consolidation)
**File:** `src/embeddings.py:17-25`
Only single-text embedding. OpenAI supports batch (up to 2048). Critical for consolidation.

### E-5: No pool warm-up at startup (MEDIUM)
Pool lazily initialized on first request. Add lifespan handler.

### E-6: numpy imported for trivial type conversion (LOW)
**File:** `src/db/memories.py:9`
~150MB memory overhead. Test if `array.array('f', embedding)` works with pgvector.

### E-7: Pool sizing may be too large (LOW)
`min_size=2, max_size=10` — consider `min_size=1, max_size=5` for MCP workload. Add `statement_cache_size=0` if using PgBouncer.

### E-8: Regex patterns not pre-compiled in metadata.py (LOW)
**File:** `src/metadata.py:28-44`

### E-9: `FOR UPDATE` lock in create_memory holds through embedding INSERT (MEDIUM)
**File:** `src/db/memories.py:40-72`
Serializes concurrent writes from same user.

### E-10: No access tracking on search results (NEEDED for consolidation)
**File:** `src/db/memories.py:75-122`
Search doesn't update `access_count` / `last_accessed_at`.

### E-11: No `_resolve_user()` for tools that don't need bank (MEDIUM)
`brain_stats`, `list_banks`, `create_bank` all resolve bank unnecessarily.

### E-12: Rate limiter not async-safe for multi-worker (LOW)
**File:** `src/ratelimit.py`
Safe for single-worker async but would race with multiple workers.

## Security (5 findings)

### S-1: No UUID validation on `memory_id` in server layer (MEDIUM)
**File:** `src/server.py:296-307`
Accepts raw string from client, DB silently returns False.

### S-2: `bank_slug` from header has no length/character validation (MEDIUM)
**File:** `src/server.py:87`
Unlike `create_bank` which validates with regex, header-based slug goes unchecked.

### S-3: In-memory rate limiter bypassed on multi-instance (KNOWN)
**File:** `src/ratelimit.py`

### S-4: Consolidation LLM prompt injection risk (PLANNED)
Memory content passed to LLM during consolidation could contain injection attempts.

### S-5: Stripe webhook needs signature verification (PLANNED)
Must use `stripe.Webhook.construct_event()`.

## Priority Fix Order

1. **BUG-1**: Fix stats query timestamps (broken feature)
2. **BUG-2**: Add UUID validation to profiles.py (unhandled 500s)
3. **R-1**: Extract shared UUID parser (fixes BUG-2 and eliminates 13 duplicates)
4. **R-2**: Extract error response helper (standardizes 10+ error sites)
5. **E-2**: Add bank resolution cache (eliminates hot-path DB query)
6. **R-6/E-1**: Combine subscription + count into single query
7. **E-4**: Add batch embedding function (unblocks consolidation)
8. **Q-6/E-5**: Add lifespan handler for pool warm-up + shutdown
9. **Q-4**: Fix exception handling in create_bank
