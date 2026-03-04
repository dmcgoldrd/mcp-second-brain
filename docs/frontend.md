# Frontend

MCP Brain's frontend is a lightweight SPA built with Vite and vanilla TypeScript. It provides user authentication, profile management, bank management, and MCP client connection instructions.

## Stack

| Technology | Version | Purpose |
|-----------|---------|---------|
| [Vite](https://vitejs.dev/) | 6.2 | Build tool and dev server |
| TypeScript | 5.7 | Type-safe JavaScript |
| [@supabase/supabase-js](https://github.com/supabase/supabase-js) | 2.49.1 | Auth + DB client |
| bun | — | Package manager (lockfile: `bun.lock`) |

No UI framework — vanilla DOM manipulation with template literals.

## File Structure

```
frontend/
├── index.html                 # HTML shell, loads /src/main.ts
├── vite.config.ts             # Vite config (port 3000, ES2020 target)
├── tsconfig.json              # Strict TS config, bundler resolution
├── package.json               # Scripts: dev, build, preview, typecheck
├── bun.lock                   # Bun lockfile
├── src/
│   ├── main.ts                # SPA router, auth lifecycle, event bindings
│   ├── style.css              # Application styles
│   ├── pages/
│   │   ├── login.ts           # Login page (email + Google OAuth)
│   │   ├── signup.ts          # Signup page (email + password)
│   │   └── dashboard.ts       # Dashboard (profile, connect, banks)
│   └── lib/
│       ├── supabase.ts        # Supabase client initialization
│       └── database.types.ts  # Generated TypeScript types from Supabase schema
```

## Routing

Hash-based SPA routing with three routes:

| Route | Page | Auth Required |
|-------|------|---------------|
| `#/login` | Login form | No (redirects to dashboard if logged in) |
| `#/signup` | Signup form | No (redirects to dashboard if logged in) |
| `#/dashboard` | Main dashboard | Yes (redirects to login if not logged in) |

Default route: `#/dashboard` if authenticated, `#/login` otherwise.

Route changes are handled via `window.addEventListener('hashchange', render)`.

## Pages

### Login (`src/pages/login.ts`)

- Email + password sign-in via `supabase.auth.signInWithPassword()`
- Google OAuth via `supabase.auth.signInWithOAuth({ provider: 'google' })`
- Error display for failed auth
- Link to signup page

### Signup (`src/pages/signup.ts`)

- Email + password + confirm password form
- Client-side validation: passwords match, minimum 6 characters
- `supabase.auth.signUp()` creates the account
- Shows "Check your email for a confirmation link" on success

### Dashboard (`src/pages/dashboard.ts`)

The main page with four sections:

#### 1. Profile Header
- User email display
- Memory count badge
- Subscription status badge (`free` / `active`)
- Sign out button

#### 2. Connect Your AI
Tabbed instructions for three MCP clients:

| Client | Instructions |
|--------|-------------|
| **Claude Code** | CLI command: `claude mcp add mcp-brain --transport http {MCP_URL}` + optional JSON config |
| **Claude Desktop** | Settings > Connectors > Add Connector with URL |
| **Cursor** | MCP settings JSON config |

Each tab shows step-by-step instructions with copy-to-clipboard buttons.

JSON config format (shared by Claude Code and Cursor):
```json
{
  "mcpServers": {
    "mcp-brain": {
      "url": "http://localhost:8080/mcp/"
    }
  }
}
```

#### 3. Memory Banks List
- Lists all user banks with name, slug, default badge, and MCP URL
- MCP URL pattern: `{SUPABASE_URL}/functions/v1/mcp-brain?bank={slug}`
- Copy button for each bank's MCP URL

#### 4. Create New Bank
- Name input (display name)
- Slug input (pattern: `[a-z0-9\-]+`, auto-sanitized on submit)
- Creates bank via `supabase.from('banks').insert()`
- Refreshes bank list on success

## Auth Lifecycle

```typescript
// Listen for auth state changes
supabase.auth.onAuthStateChange((_event, session) => {
  if (session?.user) {
    currentUser = { id: session.user.id, email: session.user.email ?? '' }
  } else {
    currentUser = null
  }
  render()  // Re-render on every auth change
})

// Check existing session on page load
const { data: { session } } = await supabase.auth.getSession()
```

## Data Loading

Dashboard data is fetched in parallel from Supabase via PostgREST:

```typescript
const [profileResult, banksResult] = await Promise.all([
  supabase.from('profiles').select('*').eq('id', currentUser.id).single(),
  supabase.from('banks').select('*').eq('user_id', currentUser.id).order('created_at'),
])
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `VITE_SUPABASE_URL` | Yes | — | Supabase project URL |
| `VITE_SUPABASE_ANON_KEY` | Yes | — | Supabase anonymous key |
| `VITE_MCP_URL` | No | `http://localhost:8080/mcp/` | MCP server URL |

Accessed via `import.meta.env.VITE_*`. The Supabase client throws at startup if URL or anon key are missing.

## Development

```bash
cd frontend
bun install
bun run dev        # Start dev server on port 3000
bun run build      # Build for production (tsc + vite build)
bun run preview    # Preview production build
bun run typecheck  # Type-check without emitting
```

## Generated Types

`src/lib/database.types.ts` is generated from the Supabase schema and provides TypeScript types for all tables:

- `Tables<'banks'>`, `Tables<'memories'>`, `Tables<'profiles'>`, `Tables<'subscriptions'>`
- `Database.public.Functions.hybrid_search` with typed args and return
- `Insert<T>`, `Update<T>`, `Row<T>` variants
