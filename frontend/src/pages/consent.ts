import { supabase } from '../lib/supabase'

/**
 * OAuth consent page for MCP client authorization.
 *
 * Supabase redirects here with ?authorization_id=xxx when an MCP client
 * requests access. The user sees what the client is requesting and can
 * approve or deny.
 */

export function renderConsent(): string {
  return `
    <div class="auth-container">
      <div class="auth-card">
        <div class="auth-header">
          <h1>🧠 MCP Brain</h1>
          <p>Authorization Request</p>
        </div>
        <div id="consent-content">
          <div class="loading">Loading authorization details...</div>
        </div>
      </div>
    </div>
  `
}

export function renderConsentDetails(client: { name: string; uri: string; logo_uri: string }, scopes: string): string {
  const scopeList = scopes.split(' ').filter(Boolean)

  return `
    <div class="consent-details">
      <div class="consent-client">
        ${client.logo_uri ? `<img src="${escapeAttr(client.logo_uri)}" alt="" class="consent-client-logo" width="48" height="48" />` : ''}
        <strong>${escapeHtml(client.name || 'Unknown Application')}</strong>
        ${client.uri ? `<span class="consent-client-uri">${escapeHtml(client.uri)}</span>` : ''}
      </div>
      <p>wants access to your MCP Brain:</p>
      <ul class="consent-scopes">
        ${scopeList.map(s => `<li>${escapeHtml(s)}</li>`).join('')}
      </ul>
      <div class="consent-actions">
        <button id="consent-approve" class="btn btn-primary">Allow</button>
        <button id="consent-deny" class="btn btn-secondary">Deny</button>
      </div>
    </div>
  `
}

function renderError(message: string): string {
  return `
    <div class="consent-error">
      <p>${escapeHtml(message)}</p>
      <a href="/" class="btn btn-secondary">Return home</a>
    </div>
  `
}

function renderLoading(message: string): string {
  return `<div class="loading">${escapeHtml(message)}</div>`
}

function escapeHtml(str: string): string {
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

function escapeAttr(str: string): string {
  return str.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/'/g, '&#39;')
}

export async function initConsent(): Promise<void> {
  const contentEl = document.getElementById('consent-content')
  if (!contentEl) return

  // Extract authorization_id from query params
  const params = new URLSearchParams(window.location.search)
  const authorizationId = params.get('authorization_id')

  if (!authorizationId) {
    contentEl.innerHTML = renderError('Missing authorization_id parameter.')
    return
  }

  // Check for active session
  const { data: { session } } = await supabase.auth.getSession()
  if (!session) {
    // Redirect to login, preserving the consent URL to return to after login
    const returnUrl = window.location.pathname + window.location.search
    window.location.href = `/#/login?returnTo=${encodeURIComponent(returnUrl)}`
    return
  }

  // Fetch authorization details
  const { data, error } = await supabase.auth.oauth.getAuthorizationDetails(authorizationId)
  if (error) {
    contentEl.innerHTML = renderError(`Failed to load authorization details: ${error.message}`)
    return
  }

  // If data has redirect_url, consent was already given — auto-redirect
  if ('redirect_url' in data) {
    window.location.href = data.redirect_url
    return
  }

  // Show consent UI
  contentEl.innerHTML = renderConsentDetails(data.client, data.scope)

  // Bind approve button
  document.getElementById('consent-approve')?.addEventListener('click', async () => {
    contentEl.innerHTML = renderLoading('Approving...')
    const result = await supabase.auth.oauth.approveAuthorization(authorizationId, { skipBrowserRedirect: true })
    if (result.error) {
      contentEl.innerHTML = renderError(`Approval failed: ${result.error.message}`)
      return
    }
    if (result.data?.redirect_url) {
      window.location.href = result.data.redirect_url
    }
  })

  // Bind deny button
  document.getElementById('consent-deny')?.addEventListener('click', async () => {
    contentEl.innerHTML = renderLoading('Denying...')
    const result = await supabase.auth.oauth.denyAuthorization(authorizationId, { skipBrowserRedirect: true })
    if (result.error) {
      contentEl.innerHTML = renderError(`Denial failed: ${result.error.message}`)
      return
    }
    if (result.data?.redirect_url) {
      window.location.href = result.data.redirect_url
    }
  })
}
