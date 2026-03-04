# Plan: Implement All 14 Security Fixes from Red Team Assessment

## Context

The red team assessment (`docs/threat-model.md`) found 14 vulnerabilities: 1 CRITICAL, 5 HIGH, 5 MEDIUM, 3 LOW. Result: 7/20 PASS, 12/20 FAIL. This plan implements all 14 fixes across 9 files.

## Files to Modify

| File | Findings Fixed |
|------|---------------|
| `src/server.py` | F-02, F-03, F-04, F-07, F-08, F-10, F-11, F-12 |
| `src/config.py` | F-08, F-09, F-12, F-13 |
| `src/ratelimit.py` | F-06 |
| `src/auth/provider.py` | F-07, F-14 |
| `src/db/connection.py` | F-13 |
| `src/db/banks.py` | F-09 |
| `src/tools/memory_tools.py` | F-05 |
| `src/db/memories.py` | F-05 |
| `migrations/003_hybrid_search_bank_id.sql` (NEW) | F-01 |

## Implementation

### Step 1: `src/config.py` — Add new config constants

Add:
- `BASE_URL = os.environ.get("BASE_URL", "http://localhost:8080")`
- `MAX_METADATA_LENGTH = int(os.environ.get("MAX_METADATA_LENGTH", "10000"))`
- `MAX_BANKS_FREE = int(os.environ.get("MAX_BANKS_FREE", "10"))`
- `MAX_BANKS_PAID = int(os.environ.get("MAX_BANKS_PAID", "50"))`
- `VALID_MEMORY_TYPES = {"observation", "task", "idea", "reference", "person_note", "decision", "preference"}`
- `VALID_SOURCES = {"mcp", "slack", "manual", "import"}`
- `MAX_TAGS = 20`
- `MAX_TAG_LENGTH = 100`
- SSL warning log if `sslmode` not in `SUPABASE_DB_URL`

### Step 2: `src/server.py` — Input validation + error sanitization + base_url

**F-02: Validate memory_type** in `create_memory()` and `list_memories()`:
```python
if memory_type and memory_type not in VALID_MEMORY_TYPES:
    return json.dumps({"status": "error", "error": "invalid_memory_type", ...})
```

**F-03: Validate source** in `create_memory()`:
```python
if source not in VALID_SOURCES:
    return json.dumps({"status": "error", "error": "invalid_source", ...})
```

**F-04: Validate tags** in `create_memory()`:
```python
if tags:
    if len(tags) > MAX_TAGS:
        return json.dumps({"status": "error", ...})
    tags = [t[:MAX_TAG_LENGTH] for t in tags]
```

**F-07: Sanitize bank error** — line 74: `"Bank not found"` (remove slug reflection)

**F-08: Metadata size limit** — check `len(metadata) > MAX_METADATA_LENGTH` before `json.loads()`

**F-10: Offset validation** — `offset = max(0, offset)` in `list_memories()`

**F-11: Content length bytes** — `len(content.encode('utf-8')) > MAX_CONTENT_LENGTH`

**F-12: base_url from env** — import `BASE_URL` from config, use in `MCPBrainAuthProvider(base_url=BASE_URL)`

### Step 3: `src/ratelimit.py` — Bounded rate limiter (F-06)

Replace unbounded `defaultdict` with `OrderedDict`-based cache with max size (10,000 entries) and LRU eviction. When a new user_id arrives and cache is full, evict oldest entry.

### Step 4: `src/auth/provider.py` — Error sanitization + OIDC caching (F-07, F-14)

**F-07:** Change error response from `f"Failed to fetch OIDC metadata: {e}"` to `"Failed to fetch authorization server metadata"`. Log the actual exception with `logger.error()`.

**F-14:** Cache OIDC response with 5-minute TTL. Simple approach: module-level `_oidc_cache` dict with `data` and `expires_at` fields. Check cache before making HTTP request.

### Step 5: `src/db/connection.py` — SSL warning (F-13)

Add warning log at module level or in `get_pool()` if `sslmode` not found in `SUPABASE_DB_URL`.

### Step 6: `src/db/banks.py` — Bank creation limit (F-09)

Add `count_user_banks()` function. In `create_bank()`, check count against limit before INSERT. Requires knowing if user is paid — add `is_paid` parameter or accept a `max_banks` parameter.

Simpler approach: accept `max_banks` param from the caller (server.py resolves paid status via existing `is_subscription_active()`).

### Step 7: `src/tools/memory_tools.py` + `src/db/memories.py` — Fix TOCTOU (F-05)

Move limit check into `db.create_memory()` as an atomic transaction:
- Add `memory_limit` parameter to `db.create_memory()`
- Inside: `BEGIN` → `SELECT memory_count FROM profiles WHERE id = $1 FOR UPDATE` → check count < limit → `INSERT` → `COMMIT`
- If limit exceeded, return error dict without inserting
- Remove the separate `get_memory_count()` + `is_subscription_active()` calls from `memory_tools.py` and pass the resolved limit directly

### Step 8: `migrations/003_hybrid_search_bank_id.sql` — New migration (F-01)

Create migration that replaces `hybrid_search()` with the version that includes `p_bank_id UUID` as second parameter, and adds `AND m.bank_id = p_bank_id` to both CTEs. This matches the already-deployed function and the application code in `src/db/memories.py:73-82`.

## Verification

1. `uv run pytest` — all existing tests pass
2. `uv run ruff check src/ tests/` — no lint errors
3. Manual check: all 14 findings addressed
