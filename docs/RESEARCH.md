# MCP Brain — Market & Technical Research

## Executive Summary

Personal MCP Brain is a SaaS that gives AI users persistent memory across all AI platforms (Claude, ChatGPT, Gemini, Cursor) via MCP protocol. Users authenticate via OAuth, and their memories are stored in Supabase Postgres with pgvector for hybrid semantic/full-text search. $7.99/month via Stripe.

**Technically feasible: YES.** Supabase Auth acts as an OAuth 2.1 Authorization Server with dedicated MCP authentication support. pgvector is available on all tiers. Hybrid search is a first-class pattern.

**Market opportunity: NARROW BUT REAL.** The gap is a polished, consumer-facing MCP memory layer. No production-grade remote multi-tenant MCP memory SaaS exists today. However, the market faces platform commoditization risk (native memory in ChatGPT/Claude) and funded competition (Mem0 at $24M).

---

## Competitive Landscape

| Company | Funding | Pricing | Approach | MCP Support |
|---------|---------|---------|----------|-------------|
| **Mem0** | $24M | Free/$19/$249/mo | Memory-as-a-service API | Community bridge |
| **Zep** | $2.3M | Free/$25/$475/mo | Temporal knowledge graph | Not primary |
| **Letta** | $10M | Free/$20/$200/mo | Agent runtime with self-editing memory | Not primary |
| **Cognee** | $7.5M | Free/Developer/Enterprise | Graph + vector pipeline | Yes, native |
| **Graphlit** | Unknown | Free tier + paid | Multi-source context platform | Yes, native |
| **Open Brain** | Open source | Free ($0.10-0.30/mo hosting) | Supabase + pgvector + MCP | Core product |
| **Khoj** | Unknown | Free/$24 one-time | Personal AI second brain | Not primary |

**Key competitive insight:** Supabase's CEO is an investor in Mem0. Building a competitor on their platform is strategically awkward but not blocking — Supabase is a platform, not a competitor.

### Inspiration: Open Brain by Nate B. Jones

YouTube: https://www.youtube.com/watch?v=2JiMmye2ezg
GitHub: https://github.com/benclawbot/open-brain

- Uses Supabase + pgvector + TypeScript/Deno + OpenRouter
- Free tier architecture ($0.10-0.30/month for embedding API calls)
- MIT licensed, 45-minute setup, no coding required
- Slack capture → embedding + metadata extraction → MCP retrieval
- 4 MCP tools: semantic search, recent thoughts, statistics, direct capture
- Thought classification: observation, task, idea, reference, person_note

---

## Pricing Analysis

### Unit Economics at $7.99/month

| Metric | Value |
|--------|-------|
| Gross revenue per subscriber | $7.99 |
| Stripe fees (2.9% + $0.30) | -$0.53 |
| Net revenue per subscriber | $7.46 |
| Supabase Pro (base) | $25/month |
| **Breakeven** | **4 subscribers** |
| Margin at 100 subscribers | 86.5% |
| Margin at 1,000 subscribers | 89.6% |

### Recommended Pricing Tiers

| Tier | Price | Memories | Retrievals | Clients |
|------|-------|----------|------------|---------|
| Free | $0 | 1,000 | 500/month | 1 |
| Personal | $7.99/month | 50,000 | Unlimited | Multiple |
| Annual | $79.99/year | Same as Personal | Same | Same |
| (Future) Pro | $14.99/month | Unlimited | Unlimited | + Graph memory |

---

## Technical Architecture

### Stack Decision

| Component | Choice | Rationale |
|-----------|--------|-----------|
| **MCP Server** | Python + UV + FastMCP | FastMCP (23k stars, ~70% market share), best AI/ML ecosystem, stable SDK |
| **Database** | Supabase Postgres + pgvector | All-in-one platform, pgvector on all tiers, RLS for isolation |
| **Auth** | Supabase Auth (OAuth 2.1 Authorization Server) | Dedicated MCP auth docs, Google OAuth, JWT + JWKS |
| **Frontend** | Static HTML/TypeScript | Minimal: auth page + payment page |
| **Billing** | Stripe | Webhook → Supabase Edge Function → subscription table |
| **Hosting (MCP Server)** | Fly.io / Railway | Long-running process, direct Postgres connection |
| **Hosting (Frontend)** | Cloudflare Pages | Free unlimited bandwidth |
| **Embeddings** | OpenAI text-embedding-3-small via API | $0.02/million tokens, 1536 dimensions |

### Architecture Diagram

```
[Claude/ChatGPT/Gemini/Cursor]
    |
    | OAuth 2.1 Authorization Code Flow
    v
[Supabase Auth] ← Google OAuth, Email/Password
    |
    | JWT Access Token
    v
[Python FastMCP Server] (Fly.io/Railway)
    |  - Streamable HTTP transport
    |  - JWT validation via Supabase JWKS
    |  - 4 MCP tools: create, search, list, delete
    |  - Embedding generation via OpenAI API
    |
    | Direct Postgres connection (asyncpg)
    v
[Supabase Postgres + pgvector]
    |  - memories table (content, embedding, metadata)
    |  - profiles table (linked to auth.users)
    |  - subscriptions table (Stripe status)
    |  - RLS policies for per-user isolation
    |  - HNSW index on embeddings
    |  - GIN index on full-text search

[Stripe] ←webhook→ [Supabase Edge Function]
                        |
                        v
                    [subscriptions table]
```

### MCP Client Compatibility

| Client | Remote MCP | OAuth 2.1 | Status |
|--------|-----------|-----------|--------|
| Claude Desktop | Yes | Yes | Fully supported |
| Claude Code | Yes | Yes | Fully supported |
| ChatGPT | Yes | Yes | Supported (May 2025+) |
| Gemini | Yes | Yes | Supported (April 2025+) |
| Cursor | Partial | Via mcp-remote | Workaround needed |
| Windsurf | Yes | Yes | Fully supported |

---

## Risk Assessment

### Critical Risks

1. **Platform commoditization**: ChatGPT, Claude, Gemini all shipping native memory. Third-party memory becomes less valuable as native memory improves.
2. **Mem0 competition**: $24M funded, 186M API calls/month, AWS partnership. Cannot out-market them.
3. **MCP spec instability**: Breaking changes every 3-6 months. Maintenance treadmill.
4. **Narrow addressable market**: Cross-platform AI power users who need shared memory is a small segment.

### Mitigating Factors

1. **Cross-platform identity persistence**: No platform will build memory that works across competitors.
2. **Data gravity**: Once memories accumulate, switching cost is real.
3. **Low infrastructure costs**: Breakeven at 4 subscribers, 85%+ margins at scale.
4. **Open source leverage**: Can open-source the core and monetize hosting.

---

## Sources

- [Mem0 $24M raise - TechCrunch](https://techcrunch.com/2025/10/28/mem0-raises-24m)
- [Open Brain GitHub](https://github.com/benclawbot/open-brain)
- [Supabase MCP Auth Docs](https://supabase.com/docs/guides/auth/oauth-server/mcp-authentication)
- [MCP Specification](https://modelcontextprotocol.io/specification/2025-03-26)
- [Supabase pgvector Docs](https://supabase.com/docs/guides/ai)
- [Supabase Hybrid Search](https://supabase.com/docs/guides/ai/hybrid-search)
- [FastMCP GitHub](https://github.com/jlowin/fastmcp)
- [Zuplo State of MCP Report](https://zuplo.com/mcp-report)
- [PulseMCP Statistics](https://www.pulsemcp.com/statistics)
