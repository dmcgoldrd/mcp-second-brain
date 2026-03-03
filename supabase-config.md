# Supabase Project Setup

## 1. Create Supabase Project

1. Go to https://supabase.com/dashboard
2. Create a new project
3. Note your project URL and keys from Settings > API

## 2. Enable pgvector

pgvector is enabled by default on all Supabase tiers. The migration script
runs `CREATE EXTENSION IF NOT EXISTS vector;` to ensure it's available.

## 3. Run Migrations

Go to SQL Editor in Supabase Dashboard and run:
- `migrations/001_initial_schema.sql`

This creates:
- `profiles` table (linked to auth.users)
- `memories` table (with vector, full-text, and JSONB columns)
- `subscriptions` table (Stripe data)
- RLS policies for per-user data isolation
- HNSW vector index and GIN full-text index
- `hybrid_search` RPC function
- Auto-triggers for profile creation and memory counting

## 4. Configure Auth

### Google OAuth
1. Go to Authentication > Providers > Google
2. Enable Google provider
3. Add your Google OAuth credentials (from Google Cloud Console)
4. Set redirect URL to your frontend domain

### OAuth 2.1 Server (for MCP clients)
1. Go to Authentication > OAuth Clients
2. Enable OAuth 2.1 Server (public beta)
3. MCP clients will auto-discover via `/.well-known/oauth-authorization-server`
4. See: https://supabase.com/docs/guides/auth/oauth-server/mcp-authentication

## 5. Stripe Integration

### Create Stripe Products
1. Create a product "MCP Brain Personal" at $7.99/month
2. Note the Price ID (starts with `price_`)

### Stripe Webhook (via Supabase Edge Function)
Deploy an Edge Function to handle Stripe webhooks:
- `checkout.session.completed` → create subscription record
- `customer.subscription.updated` → update status
- `customer.subscription.deleted` → mark canceled

## 6. Environment Variables

Copy `.env.example` to `.env` and fill in:
- `SUPABASE_URL` → from Settings > API
- `SUPABASE_ANON_KEY` → from Settings > API
- `SUPABASE_SERVICE_ROLE_KEY` → from Settings > API (keep secret!)
- `SUPABASE_DB_URL` → from Settings > Database > Connection String (use pooler port 6543)
- `OPENAI_API_KEY` → from platform.openai.com
- `STRIPE_SECRET_KEY` → from Stripe Dashboard
- `STRIPE_PRICE_ID` → from Stripe Products
