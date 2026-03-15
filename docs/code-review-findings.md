# Code Review Findings — MCP Brain src/

Review of all 11 source files for reuse, quality, efficiency, and security.

## Code Reuse

### R-1: Duplicated UUID parsing (HIGH)
**Files:** `db/memories.py`, `db/banks.py`, `db/profiles.py`
**Issue:** Every DB function has identical UUID parsing boilerplate:
```python
try:
    user_uuid = uuid.UUID(user_id)
except ValueError:
    return []  # or None, or 0, or False — inconsistent!
```
**Fix:** Extract to a shared utility:
```python
# db/utils.py
def parse_uuid(value: str, field_name: str = "id") -> uuid.UUID:
    """Parse a UUID string, raising ValueError with context on failure."""
    try:
        return uuid.UUID(value)
    except ValueError:
        raise ValueError(f"Invalid {field_name} format: expected UUID")
```
Then use consistently with a decorator or early return pattern. The inconsistent return types ([], None, 0, False, dict) on parse failure are a maintenance hazard.

### R-2: Pool acquisition pattern (LOW)
**Files:** All db/ modules
**Issue:** `pool = await get_pool()` at the start of every function. Not a bug but could become one if pool initialization changes.
**Fix:** Consider a thin base class or module-level pool reference, but this is low priority.

## Code Quality

### Q-1: Deprecated datetime usage (MEDIUM)
**File:** `metadata.py:46`
**Issue:** `datetime.utcnow()` is deprecated since Python 3.12.
**Fix:** `datetime.now(timezone.utc)` or `datetime.now(UTC)`.

### Q-2: Inconsistent error handling (MEDIUM)
**Files:** `db/memories.py` vs `server.py`
**Issue:** DB layer returns error dicts (`{"error": "..."}`) for some failures but lets exceptions propagate for others (e.g., `profiles.py:is_subscription_active()` would raise `ValueError` if UUID is invalid, not caught). Server layer returns JSON error strings.
**Fix:** Standardize: DB layer raises exceptions, tools layer catches and formats. Or: DB layer always returns Result types.

### Q-3: Magic numbers in heuristic classifier (LOW)
**File:** `metadata.py:58-71`
**Issue:** Keyword lists for memory type classification are inline, not configurable.
**Fix:** Move to config.py as `MEMORY_TYPE_KEYWORDS` dict. Low priority — these will likely be replaced by LLM classification.

### Q-4: Missing type narrowing on pool operations (LOW)
**File:** `db/memories.py:93-104`
**Issue:** `hybrid_search` call returns rows but no validation that expected columns exist.
**Fix:** Add type annotations or row validation. Low priority — DB schema enforces this.

## Efficiency

### E-1: Two separate DB queries for subscription check (MEDIUM)
**File:** `tools/memory_tools.py:31-37`
**Issue:** `is_subscription_active(user_id)` and `get_memory_count(user_id)` are two separate DB roundtrips. They could be a single query.
**Fix:**
```python
async def get_user_limits(user_id: str) -> tuple[bool, int]:
    """Get subscription status and memory count in one query."""
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT subscription_status, memory_count FROM profiles WHERE id = $1::uuid",
        uuid.UUID(user_id),
    )
    is_paid = row["subscription_status"] == "active" if row else False
    count = row["memory_count"] if row else 0
    return is_paid, count
```

### E-2: No access tracking on search (NEEDED for consolidation)
**File:** `db/memories.py:75-122`
**Issue:** `search_memories()` doesn't update `access_count` or `last_accessed_at` on returned memories. This data is needed for importance scoring in consolidation.
**Fix:** After fetching results, fire an async UPDATE for returned memory IDs. Use `asyncio.create_task()` to avoid blocking the search response.

### E-3: Embedding not cached across create+conflict check
**Issue:** When we add on-write conflict detection, the embedding generated for the new memory should be reused for the similarity search — not generated twice.
**Fix:** Already handled in the architecture design (generate embedding once, use for both insert and similarity search).

### E-4: Rate limiter doesn't persist across restarts (KNOWN)
**File:** `ratelimit.py`
**Issue:** In-memory token buckets reset on deploy. Known limitation, documented in deployment.md.
**Fix:** Acceptable for single-process. For multi-process, would need Redis. Low priority.

## Security

### S-1: Service role key for consolidation endpoint (PLANNED)
**Issue:** The planned `/api/consolidate` endpoint needs auth. Using `SUPABASE_SERVICE_ROLE_KEY` as `X-Service-Key` is acceptable for server-to-server auth but must use constant-time comparison.
**Fix:** Use `hmac.compare_digest()` for key comparison, not `==`.

### S-2: Stripe webhook signature verification (PLANNED)
**Issue:** The planned Stripe webhook handler must verify the `Stripe-Signature` header.
**Fix:** Use `stripe.Webhook.construct_event()` with the webhook signing secret.

### S-3: Bulk import rate limiting (PLANNED)
**Issue:** `import_memories` could be used to flood the system with thousands of memories in one call.
**Fix:** Limit batch size (max 100 per call), rate limit per user, count against memory limit.

### S-4: Consolidation LLM prompt injection (MEDIUM)
**Issue:** Memory content is passed to LLM during consolidation conflict resolution. Malicious memory content could include prompt injection attempts.
**Fix:** Sanitize memory content before passing to LLM. Use structured output mode. Limit content length in LLM prompts.

## Architecture Readiness

### For Conflict Detection:
- Embedding pipeline is ready (generate once, reuse for similarity + insert)
- Need: similarity search query addition to create flow
- Need: conflict response format in MCP tool

### For Consolidation:
- Need: access_count and last_accessed_at tracking on search
- Need: importance_score, archived_at, superseded_by columns
- Need: consolidation_log table
- Pool size (min=2, max=10) is fine for current load but may need tuning for batch consolidation

### For Entity Extraction:
- Need: memory_entities table
- JSONB metadata column already exists for storing entity references per-memory
- FTS index exists for entity name search

## Summary

**Critical fixes before new features:** R-1 (UUID parsing), E-1 (combined query), Q-2 (error handling consistency)
**Needed for consolidation:** E-2 (access tracking)
**Planned features have no security blockers** — standard mitigations (hmac compare, Stripe signature, rate limits, prompt sanitization)
**Architecture is clean** — the existing codebase is well-structured and ready for extension
