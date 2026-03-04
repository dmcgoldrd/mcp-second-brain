# Plan: "Connect Your AI" Dashboard Section

## Context

Users who log into the dashboard can see their banks and profile, but have no guidance on how to actually connect their AI tools to the MCP server. The `CONNECTING.md` doc exists for developers, but end users need a copy-paste config block right in the UI, pre-filled with their JWT.

## What We're Building

A new card on the dashboard between Profile and Memory Banks that shows:
1. **Pill-tab selector** — Claude Code / Claude Desktop / Cursor
2. **JSON code block** — the correct MCP config with the user's live JWT pre-filled
3. **Per-client instructions** — where to put the config file (path differs per client)
4. **Copy button** — one click to clipboard
5. **JWT expiry note** — reminder that tokens expire

The JSON blob shape is identical across all three clients — only the file path instructions differ.

## Files to Modify

### 1. `frontend/src/pages/dashboard.ts`

- Export `ConnectClient` type: `'claude-code' | 'claude-desktop' | 'cursor'`
- Add `MCP_URL` constant from `VITE_MCP_URL` env var (default `http://localhost:8080/mcp/`)
- Add `CLIENT_INFO` map with label + instructions per client
- Export `getClientConfig(client, jwt)` — returns formatted JSON string
- Export `getClientInstructions(client)` — returns HTML string with file paths
- Add `renderConnectSection(jwt, activeClient)` — builds the card HTML
- Update `renderDashboard()` signature: add `jwt?: string` and `activeClient?: ConnectClient`
- Insert `renderConnectSection()` output between Profile and Memory Banks cards

The code block copy uses a `data-connect-copy` attribute on the button; the JS handler reads `#connect-config-code`'s `textContent` directly (avoids escaping issues with storing JSON in HTML attributes).

### 2. `frontend/src/main.ts`

- Import `getClientConfig`, `getClientInstructions`, `ConnectClient` from dashboard
- Add module-level `activeConnectClient: ConnectClient = 'claude-code'`
- Add module-level `currentJwt = ''`
- Update `loadDashboardData()`: fetch session via `supabase.auth.getSession()` in parallel, pass `currentJwt` and `activeConnectClient` to `renderDashboard()`
- Update `onAuthStateChange`: capture `session.access_token` into `currentJwt`
- Update `init()`: capture JWT from initial session
- Add `bindConnectSection()`: tab click handlers (targeted DOM update — swap code block + instructions without full re-render) and copy button handler (reads from `#connect-config-code.textContent`)
- Call `bindConnectSection()` after dashboard renders

### 3. `frontend/src/style.css`

New classes:
- `.connect-tabs` — flex row with gap, wraps on narrow screens
- `.connect-tab` — pill button (border, rounded-full, muted text)
- `.connect-tab--active` — accent background, white text
- `.connect-code-block` — relative container, bg dark, border, radius
- `.connect-code-block pre` — monospace, padding, overflow-x scroll
- `.connect-copy-btn` — absolute top-right, surface bg
- `.connect-instructions` — small text with styled `<code>` elements
- `.connect-note` — small text with left border accent

## Verification

1. `cd frontend && bun run dev` — start Vite dev server
2. Log in → dashboard should show Connect card between Profile and Banks
3. Click each tab — code block and instructions update without page reload
4. Copy button — copies valid JSON to clipboard with real JWT
5. JWT is present in config (not placeholder) after data loads
6. Narrow the browser — tabs should wrap gracefully
7. `bun run build` — no TypeScript errors
