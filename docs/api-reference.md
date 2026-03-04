# API Reference

MCP Brain exposes 7 tools via the MCP protocol. All tools require a valid Supabase JWT as a Bearer token. All tools return JSON strings.

## Authentication

Every tool receives an `AccessToken` injected by FastMCP via `CurrentAccessToken()`. The token's `sub` claim provides the `user_id`. Bank selection is determined by the `x-bank-slug` HTTP header, falling back to the user's default bank.

See [authentication.md](authentication.md) for full details.

## Rate Limits

| Limiter | Capacity | Refill Rate | Applies To |
|---------|----------|-------------|------------|
| `tool_limiter` | 60 tokens | 1/sec | All tools (checked in `_resolve_auth`) |
| `embedding_limiter` | 30 tokens | 0.5/sec | `create_memory`, `search_memories` |

Rate limiting is per-user, in-memory, and resets on server restart.

---

## `create_memory`

Store a new memory in your Personal Brain. The content is embedded for semantic search, auto-classified by type, and enriched with extracted metadata.

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `content` | `str` | **required** | The memory text to store. Be descriptive and specific. |
| `memory_type` | `str \| None` | `None` | One of: `observation`, `task`, `idea`, `reference`, `person_note`, `decision`, `preference`. Auto-classified if not provided. |
| `tags` | `list[str] \| None` | `None` | Tags for categorization. Example: `["work", "python", "architecture"]` |
| `metadata` | `str \| None` | `None` | Additional metadata as JSON string. Example: `{"entities": ["Alice", "Acme Corp"], "topics": ["hiring"]}` |
| `source` | `str` | `"mcp"` | Origin of the memory: `mcp`, `slack`, `manual`, `import` |

### Processing Pipeline

1. Content length check (max 50,000 characters)
2. Parse `metadata` JSON string (invalid JSON wrapped as `{"raw": "..."}`)
3. Check subscription memory limit (free: 1,000 / paid: 50,000)
4. Check embedding rate limit (30/min)
5. Generate 1536-dim embedding via OpenAI `text-embedding-3-small`
6. Auto-classify `memory_type` if not provided (keyword heuristics)
7. Extract metadata (word count, URLs, @mentions, dates)
8. Merge user-provided metadata over auto-extracted metadata
9. Insert into database

### Response — Success

```json
{
  "status": "created",
  "memory_id": "550e8400-e29b-41d4-a716-446655440000",
  "memory_type": "task",
  "tags": ["work"]
}
```

### Response — Errors

```json
{"status": "error", "error": "content_too_long", "message": "Content exceeds 50000 character limit."}
```

```json
{"status": "error", "error": "memory_limit_reached", "message": "You have 1000/1000 memories. Upgrade your plan for more."}
```

```json
{"status": "error", "error": "rate_limited", "message": "Embedding rate limit exceeded. Please slow down."}
```

---

## `search_memories`

Search your Personal Brain using hybrid semantic + full-text search with Reciprocal Ranked Fusion (RRF) scoring.

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `query` | `str` | **required** | Natural language search query. Example: `"What did I decide about the database architecture?"` |
| `limit` | `int` | `10` | Maximum results to return. Clamped to 1-50. |

### Processing

1. Check embedding rate limit
2. Generate embedding for the query
3. If query text is non-empty: call PostgreSQL `hybrid_search()` function (RRF combining cosine similarity + full-text search)
4. If query text is empty: pure cosine similarity search

### Response

```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "content": "Decided to use pgvector for semantic search",
    "memory_type": "decision",
    "tags": ["architecture", "database"],
    "score": 0.923,
    "created_at": "2024-03-01T12:00:00"
  }
]
```

Returns `[]` if rate limited (silent).

---

## `list_memories`

List recent memories in reverse chronological order. Optionally filter by type.

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `limit` | `int` | `20` | Results per page. Clamped to 1-100. |
| `offset` | `int` | `0` | Pagination offset. |
| `memory_type` | `str \| None` | `None` | Filter by type: `observation`, `task`, `idea`, `reference`, `person_note`, `decision`, `preference` |

### Response

```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "content": "Met with Alice about the hiring plan",
    "memory_type": "person_note",
    "tags": ["hiring"],
    "source": "mcp",
    "created_at": "2024-03-01T12:00:00"
  }
]
```

---

## `delete_memory`

Delete a specific memory by UUID.

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `memory_id` | `str` | **required** | The UUID of the memory to delete. |

### Response — Deleted

```json
{"status": "deleted", "memory_id": "550e8400-e29b-41d4-a716-446655440000"}
```

### Response — Not Found

```json
{"status": "not_found", "memory_id": "550e8400-e29b-41d4-a716-446655440000"}
```

The DELETE is scoped to the authenticated user and current bank — users cannot delete other users' memories.

---

## `brain_stats`

Get statistics about your Personal Brain for the current bank.

### Parameters

None (besides the injected auth token).

### Response

```json
{
  "total_memories": 42,
  "type_breakdown": {
    "observation": 20,
    "task": 15,
    "idea": 7
  },
  "oldest_memory": "2024-01-01T00:00:00",
  "newest_memory": "2024-12-31T00:00:00"
}
```

Dates are `null` when no memories exist.

---

## `list_banks`

List all memory banks for the authenticated user.

### Parameters

None (besides the injected auth token).

### Response

```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "name": "Personal",
    "slug": "personal",
    "is_default": true,
    "created_at": "2024-01-01T00:00:00"
  },
  {
    "id": "660e8400-e29b-41d4-a716-446655440001",
    "name": "Work",
    "slug": "work",
    "is_default": false,
    "created_at": "2024-06-01T00:00:00"
  }
]
```

Banks are ordered: default bank first, then by creation date ascending.

---

## `create_bank`

Create a new memory bank to organize memories into separate collections.

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `name` | `str` | **required** | Display name. Example: `"Work Projects"` |
| `slug` | `str` | **required** | URL-safe identifier. Lowercase, no spaces. Example: `"work"` |

### Response — Success

```json
{
  "status": "created",
  "bank_id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "Work Projects",
  "slug": "work"
}
```

### Response — Duplicate Slug

```json
{"status": "error", "message": "Bank slug 'work' already exists"}
```

New banks are created with `is_default = false`. The `(user_id, slug)` pair must be unique.

---

## Memory Type Auto-Classification

When `memory_type` is not provided to `create_memory`, the server classifies it using keyword heuristics. First match wins:

| Priority | Type | Trigger Keywords |
|----------|------|------------------|
| 1 | `task` | `todo`, `task`, `need to`, `should`, `must`, `deadline` |
| 2 | `idea` | `idea:`, `what if`, `maybe we`, `concept:`, `brainstorm` |
| 3 | `reference` | `http://`, `https://`, `reference:`, `link:`, `source:` |
| 4 | `decision` | `decided`, `decision:`, `chose`, `going with`, `picked` |
| 5 | `preference` | `prefer`, `always`, `never`, `i like`, `i hate`, `i want` |
| 6 | `person_note` | `met with`, `spoke to`, `talked to`, `said that`, `person:` |
| 7 | `observation` | Default fallback |

## Auto-Extracted Metadata

The server extracts metadata from memory content using regex heuristics. This is merged with any user-provided `metadata` (user-provided values overwrite auto-extracted on key collision):

| Field | Condition | Example |
|-------|-----------|---------|
| `word_count` | Always | `42` |
| `indexed_at` | Always | `"2024-03-01T12:00:00"` |
| `urls` | If URLs found | `["https://example.com"]` |
| `mentions` | If @mentions found | `["alice", "bob"]` |
| `referenced_dates` | If dates found | `["2024-03-01", "3/15/2024"]` |
