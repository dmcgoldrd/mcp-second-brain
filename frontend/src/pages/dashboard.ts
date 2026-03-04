import type { Tables } from '../lib/database.types'

type Profile = Tables<'profiles'>
type Bank = Tables<'banks'>

export type ConnectClient = 'claude-code' | 'claude-desktop' | 'cursor'

const SUPABASE_URL = import.meta.env.VITE_SUPABASE_URL
const MCP_URL = (import.meta.env.VITE_MCP_URL as string | undefined) ?? 'http://localhost:8080/mcp/'

interface ClientMeta {
  label: string
  steps: string[]
  hasJsonConfig: boolean
}

function claudeCodeCmd(): string {
  return `claude mcp add mcp-brain --transport http ${MCP_URL}`
}

const CLIENT_INFO: Record<ConnectClient, ClientMeta> = {
  'claude-code': {
    label: 'Claude Code',
    hasJsonConfig: true,
    steps: [
      '__CMD__',
      'Run <code>/mcp</code> in Claude Code to verify the connection.',
    ],
  },
  'claude-desktop': {
    label: 'Claude Desktop',
    hasJsonConfig: false,
    steps: [
      'Open <strong>Settings</strong> &rarr; <strong>Connectors</strong>',
      `Click <strong>Add Connector</strong> and enter the URL:<div class="connect-cmd"><code>${MCP_URL}</code><button class="connect-cmd-copy" data-connect-copy-cmd>Copy</button></div>`,
      'Save and complete the authentication flow when prompted.',
    ],
  },
  cursor: {
    label: 'Cursor',
    hasJsonConfig: true,
    steps: [
      'Open <strong>Cursor Settings</strong> &rarr; <strong>MCP</strong> &rarr; <strong>Add new global MCP server</strong>',
      'Paste the configuration below.',
      'Save and restart Cursor.',
    ],
  },
}

export function getClientConfig(_client: ConnectClient): string {
  return JSON.stringify({ mcpServers: { 'mcp-brain': { url: MCP_URL } } }, null, 2)
}

export function getClientSteps(client: ConnectClient): string {
  return CLIENT_INFO[client].steps
    .map((step, i) => {
      let content = step
      if (step === '__CMD__') {
        const cmd = claudeCodeCmd()
        content = `Run this in your terminal:<div class="connect-cmd"><code>${cmd}</code><button class="connect-cmd-copy" data-connect-copy-cmd>Copy</button></div>`
      }
      return `<li><span class="step-num">${i + 1}</span><span>${content}</span></li>`
    })
    .join('')
}

export function clientHasJsonConfig(client: ConnectClient): boolean {
  return CLIENT_INFO[client].hasJsonConfig
}

function renderConnectSection(activeClient: ConnectClient): string {
  const tabs = (Object.keys(CLIENT_INFO) as ConnectClient[])
    .map(
      (key) =>
        `<button class="connect-tab${activeClient === key ? ' connect-tab--active' : ''}" data-client-tab="${key}">${CLIENT_INFO[key].label}</button>`,
    )
    .join('')

  const showJson = clientHasJsonConfig(activeClient)
  const configJson = escapeHtml(getClientConfig(activeClient))
  const showJsonAlt = activeClient === 'claude-code'

  return `
    <div class="card">
      <h2>Connect Your AI</h2>
      <div class="connect-tabs">${tabs}</div>
      <ol class="connect-steps" id="connect-steps">${getClientSteps(activeClient)}</ol>
      ${showJsonAlt ? '<div class="divider" id="connect-divider">or add JSON config manually</div>' : ''}
      <div class="connect-code-block${showJson ? '' : ' hidden'}" id="connect-code-wrapper">
        <pre><code id="connect-config-code">${configJson}</code></pre>
        <button class="connect-copy-btn" data-connect-copy>Copy</button>
      </div>
    </div>
  `
}

function getMcpUrl(slug: string): string {
  return `${SUPABASE_URL}/functions/v1/mcp-brain?bank=${slug}`
}

function renderBankItem(bank: Bank): string {
  const mcpUrl = getMcpUrl(bank.slug)
  return `
    <div class="bank-item">
      <h3>${escapeHtml(bank.name)}</h3>
      <span class="slug">${escapeHtml(bank.slug)}</span>
      ${bank.is_default ? ' <span class="badge badge-free">default</span>' : ''}
      <div class="mcp-url">
        <span>${escapeHtml(mcpUrl)}</span>
        <button class="copy-btn" data-copy-url="${escapeAttr(mcpUrl)}">Copy</button>
      </div>
    </div>
  `
}

function renderBanksList(banks: Bank[] | null, loading: boolean): string {
  if (loading) {
    return '<p class="text-muted"><span class="spinner"></span> Loading banks...</p>'
  }

  if (!banks || banks.length === 0) {
    return '<p class="text-muted">No memory banks yet. Create one below.</p>'
  }

  return banks.map(renderBankItem).join('')
}

function renderProfileInfo(profile: Profile | null, loading: boolean): string {
  if (loading) {
    return '<span class="spinner"></span>'
  }

  if (!profile) {
    return '<p class="text-muted">Could not load profile.</p>'
  }

  const status = profile.subscription_status ?? 'free'
  const badgeClass = status === 'active' ? 'badge-active' : 'badge-free'
  const memoryCount = profile.memory_count ?? 0

  return `
    <p class="text-muted">
      ${memoryCount} memor${memoryCount === 1 ? 'y' : 'ies'} stored
      <span class="badge ${badgeClass}">${escapeHtml(status)}</span>
    </p>
  `
}

export function renderDashboard(
  profile: Profile | null,
  banks: Bank[] | null,
  loading: boolean,
  userEmail?: string,
  activeClient?: ConnectClient,
): string {
  const email = userEmail ?? profile?.display_name ?? ''

  return `
    <div class="profile-header">
      <div>
        <h1>MCP <span class="accent">Brain</span></h1>
        ${loading ? '' : `<p class="text-muted">${escapeHtml(email)}</p>`}
      </div>
      <button id="logout-btn" class="btn btn-danger btn-sm">Sign Out</button>
    </div>

    <div class="card">
      <h2>Profile</h2>
      ${renderProfileInfo(profile, loading)}
    </div>

    ${renderConnectSection(activeClient ?? 'claude-code')}

    <div class="card">
      <h2>Memory Banks</h2>
      <div id="banks-list">
        ${renderBanksList(banks, loading)}
      </div>
    </div>

    <div class="card">
      <h2>Create New Bank</h2>
      <form id="create-bank-form">
        <div class="form-group">
          <label for="bank-name">Bank Name</label>
          <input type="text" id="bank-name" placeholder="Work Notes" required />
        </div>
        <div class="form-group">
          <label for="bank-slug">Slug</label>
          <input type="text" id="bank-slug" placeholder="work-notes" required pattern="[a-z0-9\\-]+" />
        </div>
        <div id="create-bank-error" class="error-msg"></div>
        <button type="submit" class="btn btn-primary mt-1">Create Bank</button>
      </form>
    </div>
  `
}

function escapeHtml(str: string): string {
  const div = document.createElement('div')
  div.textContent = str
  return div.innerHTML
}

function escapeAttr(str: string): string {
  return str.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/'/g, '&#39;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}
