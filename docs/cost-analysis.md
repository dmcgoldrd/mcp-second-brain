# MCP Brain Consolidation — Cost Analysis & Alternatives

## Current Architecture Cost Model

### Per-Phase Costs

| Phase | Operation | API Calls | Cost Driver | Scalable? |
|-------|-----------|-----------|-------------|-----------|
| **1. Scoring** | SQL UPDATE | 0 | Postgres CPU | Yes — single query regardless of N |
| **2. Dedup** | SQL self-join | 0 | Postgres CPU | Yes after incremental fix (K*N not N^2) |
| **3. Conflicts** | LLM classify per pair | 1 per ambiguous pair | **OpenAI API** | No — linear in conflict count |
| **4. Entities** | LLM extract per batch of 10 | 1 per 10 unprocessed memories | **OpenAI API** | No — linear in new memories |
| **5. Archive** | SQL UPDATE | 0 | Postgres CPU | Yes |

**The bill is Phases 3 + 4.** Everything else is pennies.

### Token Budget Per Call

**Phase 3 — Conflict Classification (gpt-4o-mini):**
- Prompt: ~150 tokens (system) + ~100 tokens per memory × 2 = ~350 tokens input
- Response: ~5 tokens (just "UPDATE" or "KEEP_BOTH")
- Total: ~355 tokens per pair
- max_tokens: 10

**Phase 4 — Entity Extraction (gpt-4o-mini, batches of 10):**
- Prompt: ~100 tokens (system) + ~100 tokens per memory × 10 = ~1,100 tokens input
- Response: ~200-500 tokens (JSON array of entities)
- Total: ~1,400 tokens per batch
- max_tokens: 2,000

### gpt-4o-mini Pricing (March 2026)

| | Input | Output | Cached Input |
|--|-------|--------|-------------|
| gpt-4o-mini | $0.15/1M tokens | $0.60/1M tokens | $0.075/1M |

### Cost Per User Per Night (Incremental Model)

Assume: user adds **20 memories/day**, has **1,000 total active memories**.

| Phase | What Happens | LLM Calls | Tokens | Cost |
|-------|-------------|-----------|--------|------|
| 1. Scoring | UPDATE 20 rows | 0 | 0 | $0.00 |
| 2. Dedup | 20 new vs 1000 vault. ~2 pairs above 0.90 threshold | 0 | 0 | $0.00 |
| 3. Conflicts | ~5 pairs in 0.80-0.90 band | 5 | ~1,775 | **$0.0003** |
| 4. Entities | 20 new memories / 10 per batch = 2 batches | 2 | ~2,800 | **$0.0005** |
| 5. Archive | Scan for stale | 0 | 0 | $0.00 |
| **Total** | | **7 LLM calls** | **~4,575 tokens** | **$0.0008** |

### Cost at Scale

| Users | Memories/user/day | Nightly Cost | Monthly Cost | Annual Cost |
|-------|-------------------|-------------|-------------|-------------|
| 10 | 20 | $0.008 | $0.24 | $2.88 |
| 100 | 20 | $0.08 | $2.40 | $28.80 |
| 1,000 | 20 | $0.80 | $24.00 | $288 |
| 10,000 | 20 | $8.00 | $240 | $2,880 |
| 100,000 | 20 | $80.00 | $2,400 | $28,800 |

**At 1,000 users: $24/month in LLM costs for consolidation.** This is nothing compared to $7,990/month in subscription revenue (1,000 × $7.99).

### But Wait — The Real Cost Isn't Consolidation

The **dominant cost** is actually the **on-write embedding generation** via OpenAI, not consolidation:

| Operation | Per-call cost | Daily (20 memories/user) | Monthly (1K users) |
|-----------|-------------|--------------------------|-------------------|
| **Embedding (create_memory)** | ~$0.000003 per memory | $0.00006/user | $1.80 |
| **Embedding (search_memories)** | ~$0.000003 per search | $0.00015/user (50 searches) | $4.50 |
| **Consolidation LLM** | ~$0.0008/user | $0.0008/user | $24.00 |
| **Supabase Postgres** | Fixed | Fixed | $25.00 |

**Total infrastructure at 1,000 users: ~$55/month** vs **$7,990/month revenue** = **99.3% margin**.

Consolidation is 44% of infrastructure cost but a rounding error on revenue.

---

## Where This Breaks (10K+ Users)

| Concern | Threshold | Impact |
|---------|-----------|--------|
| OpenAI rate limits | ~3,000 RPM for gpt-4o-mini | 10K users × 7 calls = 70K calls. At 3K RPM, takes ~23 min. Acceptable. |
| Postgres connections | 60 max on Supabase Pro | 5 concurrent users × 1 conn each = 5 conns. Fine. |
| Wall-clock time | 10K users × ~2s each | ~5.5 hours with 5 concurrent. Getting long. |
| OpenAI spend | $80/night | $2,400/month. Still 97% margin but noticeable. |

**The real limit is wall-clock time.** At 10K users, consolidation takes hours. At 100K users, it can't finish in one night.

---

## Alternative Architectures (Creative Options)

### Option A: Eliminate Phase 3 LLM Entirely — Heuristic Conflict Resolution

**Current:** LLM classifies each conflict pair as UPDATE or KEEP_BOTH.
**Alternative:** Use deterministic rules instead.

```python
def heuristic_conflict_resolution(memory_a, memory_b, similarity):
    # Same memory_type + high similarity + >30 days apart = UPDATE
    if (similarity > 0.85 and
        days_between(memory_a, memory_b) > 30 and
        memory_a.memory_type == memory_b.memory_type):
        return "UPDATE"  # newer wins

    # Same content but different tags = KEEP_BOTH (user categorized differently)
    if memory_a.tags != memory_b.tags:
        return "KEEP_BOTH"

    # Default: KEEP_BOTH (conservative)
    return "KEEP_BOTH"
```

**Cost impact:** Phase 3 drops from $0.0003/user/night to $0.00. Saves ~36% of LLM spend.
**Quality impact:** Worse at detecting nuanced fact updates ("wife is Maria" → "wife is Margaret"). But on-write conflict detection already catches these at create time — consolidation is a backup.
**Verdict:** Worth it for free-tier users. Paid users could get LLM-powered.

### Option B: Replace Phase 4 LLM with Embedding Clustering

**Current:** LLM extracts entities from memories.
**Alternative:** Use embedding similarity to cluster memories and infer entities.

```python
# Instead of LLM extraction:
# 1. Cluster memories by embedding similarity (DBSCAN or simple threshold)
# 2. Name clusters by most common nouns (spaCy NER, free, runs locally)
# 3. Store cluster centers as "entities"
```

**Cost impact:** Phase 4 drops to $0.00. Eliminates 64% of LLM spend.
**Quality impact:** Worse entity extraction quality. But entities are a nice-to-have, not core.
**Verdict:** Good for v1. Upgrade to LLM extraction when revenue justifies it.

### Option C: Move LLM Calls to Client Side — "Smart Write"

**Current:** Server runs LLM in consolidation batch.
**Alternative:** The MCP client's LLM does the work at write time.

When `create_memory` detects conflicts (which it already does), return the conflicts and let the calling AI resolve them:

```
AI: "I noticed you stored 'wife is Maria' but now you said 'wife is Margaret'.
     Should I update the old memory?"
User: "Yes"
AI: calls update_memory to supersede
```

**Cost impact:** Consolidation LLM cost drops to $0.00. The client's LLM (which the user is already paying for) does the work.
**Quality impact:** Better — the client has full conversation context. Our consolidation LLM only sees two short memories.
**Verdict:** Best option for conflict resolution. We already return conflicts in create_memory responses — the client just needs to act on them.

### Option D: Tiered Consolidation

| Tier | Frequency | Phases | LLM? | Cost |
|------|-----------|--------|------|------|
| Free | Weekly | 1, 2, 5 only | No | $0.00 |
| Personal ($7.99) | Nightly | 1, 2, 3, 5 | Heuristic only | $0.00 |
| Pro ($14.99) | Nightly | All 5 | Full LLM | ~$0.024/mo |
| Enterprise | On-demand | All 5 + custom | Full LLM | Usage-based |

**This aligns cost with revenue.** Free users get dedup and archival. Paid users get conflict resolution. Pro gets entity extraction.

### Option E: Local Small Model Instead of OpenAI API

Run a small classification model locally instead of calling gpt-4o-mini:

| Option | Model | Hosting | Cost/call | Quality |
|--------|-------|---------|-----------|---------|
| gpt-4o-mini (current) | API | OpenAI | $0.0001 | High |
| Ollama (llama3.2:1b) | Local | Same server | $0.00 | Medium |
| ONNX classifier | Local | Same server | $0.00 | Low (fine-tuned) |
| Haiku 4.5 | API | Anthropic | $0.00003 | High |

**Haiku 4.5 is the best immediate swap:** 3x cheaper than gpt-4o-mini, comparable quality for classification tasks. Just change `_CLASSIFICATION_MODEL` and the client.

**Ollama is the best zero-cost option:** Run llama3.2:1b on the same Railway container. No API calls. Quality is acceptable for binary classification (UPDATE vs KEEP_BOTH).

### Option F: Event-Driven Instead of Nightly Batch

**Current:** Cron job at midnight processes all users.
**Alternative:** Trigger consolidation per-user after N new memories.

```python
# In create_memory, after inserting:
new_count = await get_memories_since_last_consolidation(user_id)
if new_count >= 50:  # threshold
    asyncio.create_task(consolidate_user(user_id, bank_id))
```

**Pros:** No idle processing. Users with 0 activity = $0. Spreads load across the day.
**Cons:** Consolidation happens during user's session (latency risk). Could trigger multiple times.
**Verdict:** Good hybrid — keep nightly as fallback, add event-driven for active users.

---

## Recommended Architecture

Combine the best ideas:

### Phase 1: Ship Now (costs ~$0)

1. **Phase 3: Switch to heuristic conflict resolution** (drop LLM)
   - On-write conflict detection already returns similar memories to the client
   - The client's LLM resolves conflicts for free (Option C)
   - Consolidation just catches anything the client missed, using time + similarity rules

2. **Phase 4: Defer entity extraction to on-demand**
   - Don't extract entities nightly — do it when `get_entities` is called
   - Cache the results. Only re-extract for new memories.
   - Or use spaCy NER locally ($0, runs in-process)

3. **Switch to Haiku 4.5** for any remaining LLM calls — 3x cheaper

### Phase 2: At Scale (1,000+ users)

4. **Tiered consolidation** (Option D) — free users get Phases 1,2,5 only
5. **Event-driven triggering** (Option F) — consolidate after 50 new memories
6. **Move entity extraction to a background worker** that runs at lowest priority

### Phase 3: At Real Scale (10K+ users)

7. **Local model** (Ollama or fine-tuned ONNX) for classification
8. **Dedicated consolidation worker** on a separate Railway service
9. **Sharded processing** — split users across multiple worker instances

---

## Cost Summary by Architecture

| Architecture | 100 users/mo | 1K users/mo | 10K users/mo | 100K users/mo |
|-------------|-------------|-------------|-------------|-------------|
| **Current (gpt-4o-mini)** | $2.40 | $24 | $240 | $2,400 |
| **Haiku 4.5 swap** | $0.80 | $8 | $80 | $800 |
| **Heuristic conflicts + Haiku entities** | $0.50 | $5 | $50 | $500 |
| **Full heuristic (no LLM)** | $0.00 | $0.00 | $0.00 | $0.00 |
| **Client-side resolution + heuristic** | $0.00 | $0.00 | $0.00 | $0.00 |

**The "client-side resolution + heuristic" option costs literally $0** and has arguably better quality because the client LLM has full conversation context.

---

## Bottom Line

Consolidation LLM costs are a non-issue until 10K+ users. At $7.99/user and $0.024/user/month in consolidation costs, the margin is 99.7%.

But the smart move is to **not pay for LLM calls at all:**
1. Let the MCP client resolve conflicts at write time (already built — conflicts returned in create_memory response)
2. Use heuristic rules for nightly cleanup (time + similarity thresholds)
3. Defer entity extraction to on-demand or use local NER

This eliminates the only variable cost in the infrastructure and makes it truly "set and forget" at any scale.
