import { supabase } from './lib/supabase'
import { renderLogin } from './pages/login'
import { renderSignup } from './pages/signup'
import { renderDashboard, getClientConfig, getClientSteps, clientHasJsonConfig } from './pages/dashboard'
import { renderConsent, initConsent } from './pages/consent'
import type { ConnectClient } from './pages/dashboard'
import './style.css'

type Route = 'login' | 'signup' | 'dashboard' | 'consent'

let currentUser: { id: string; email: string } | null = null
let activeConnectClient: ConnectClient = 'claude-code'

function getRoute(): Route {
  // OAuth consent uses real path routing (Supabase redirects to /oauth/consent)
  if (window.location.pathname === '/oauth/consent') return 'consent'

  const hash = window.location.hash.replace('#/', '').replace('#', '')
  if (hash === 'login') return 'login'
  if (hash === 'signup') return 'signup'
  if (hash === 'dashboard') return 'dashboard'
  return currentUser ? 'dashboard' : 'login'
}

function navigate(route: Route): void {
  window.location.hash = `#/${route}`
}

function render(): void {
  const app = document.getElementById('app')
  if (!app) return

  const route = getRoute()

  // Protect dashboard route
  if (route === 'dashboard' && !currentUser) {
    navigate('login')
    return
  }

  // Redirect authenticated users away from auth pages
  if ((route === 'login' || route === 'signup') && currentUser) {
    navigate('dashboard')
    return
  }

  switch (route) {
    case 'login':
      app.innerHTML = renderLogin()
      bindLoginEvents()
      break
    case 'signup':
      app.innerHTML = renderSignup()
      bindSignupEvents()
      break
    case 'dashboard':
      app.innerHTML = renderDashboard(null, null, true, currentUser?.email, activeConnectClient)
      loadDashboardData()
      bindDashboardEvents()
      bindConnectSection()
      break
    case 'consent':
      app.innerHTML = renderConsent()
      initConsent()
      break
  }
}

function bindLoginEvents(): void {
  const form = document.getElementById('login-form') as HTMLFormElement | null
  const googleBtn = document.getElementById('google-login-btn')

  form?.addEventListener('submit', async (e) => {
    e.preventDefault()
    const email = (document.getElementById('login-email') as HTMLInputElement).value
    const password = (document.getElementById('login-password') as HTMLInputElement).value
    const errorEl = document.getElementById('login-error')

    if (errorEl) errorEl.textContent = ''

    const { error } = await supabase.auth.signInWithPassword({ email, password })
    if (error && errorEl) {
      errorEl.textContent = error.message
    }
  })

  googleBtn?.addEventListener('click', async () => {
    const { error } = await supabase.auth.signInWithOAuth({
      provider: 'google',
      options: { redirectTo: window.location.origin },
    })
    if (error) {
      const errorEl = document.getElementById('login-error')
      if (errorEl) errorEl.textContent = error.message
    }
  })
}

function bindSignupEvents(): void {
  const form = document.getElementById('signup-form') as HTMLFormElement | null

  form?.addEventListener('submit', async (e) => {
    e.preventDefault()
    const email = (document.getElementById('signup-email') as HTMLInputElement).value
    const password = (document.getElementById('signup-password') as HTMLInputElement).value
    const confirm = (document.getElementById('signup-confirm') as HTMLInputElement).value
    const errorEl = document.getElementById('signup-error')
    const successEl = document.getElementById('signup-success')

    if (errorEl) errorEl.textContent = ''
    if (successEl) successEl.textContent = ''

    if (password !== confirm) {
      if (errorEl) errorEl.textContent = 'Passwords do not match'
      return
    }

    if (password.length < 6) {
      if (errorEl) errorEl.textContent = 'Password must be at least 6 characters'
      return
    }

    const { error } = await supabase.auth.signUp({ email, password })
    if (error && errorEl) {
      errorEl.textContent = error.message
    } else if (successEl) {
      successEl.textContent = 'Check your email for a confirmation link.'
    }
  })
}

function bindDashboardEvents(): void {
  const logoutBtn = document.getElementById('logout-btn')
  logoutBtn?.addEventListener('click', async () => {
    await supabase.auth.signOut()
  })

  const createForm = document.getElementById('create-bank-form') as HTMLFormElement | null
  createForm?.addEventListener('submit', async (e) => {
    e.preventDefault()
    if (!currentUser) return

    const nameInput = document.getElementById('bank-name') as HTMLInputElement
    const slugInput = document.getElementById('bank-slug') as HTMLInputElement
    const errorEl = document.getElementById('create-bank-error')

    const name = nameInput.value.trim()
    const slug = slugInput.value.trim().toLowerCase().replace(/[^a-z0-9-]/g, '-')

    if (!name || !slug) {
      if (errorEl) errorEl.textContent = 'Name and slug are required'
      return
    }

    const { error } = await supabase.from('banks').insert({
      user_id: currentUser.id,
      name,
      slug,
    })

    if (error && errorEl) {
      errorEl.textContent = error.message
    } else {
      nameInput.value = ''
      slugInput.value = ''
      if (errorEl) errorEl.textContent = ''
      loadDashboardData()
    }
  })
}

async function loadDashboardData(): Promise<void> {
  if (!currentUser) return

  const [profileResult, banksResult] = await Promise.all([
    supabase.from('profiles').select('*').eq('id', currentUser.id).single(),
    supabase.from('banks').select('*').eq('user_id', currentUser.id).order('created_at', { ascending: true }),
  ])

  const app = document.getElementById('app')
  if (!app) return

  app.innerHTML = renderDashboard(
    profileResult.data,
    banksResult.data,
    false,
    currentUser?.email,
    activeConnectClient,
  )
  bindDashboardEvents()
  bindConnectSection()

  // Bind copy buttons after render
  document.querySelectorAll('[data-copy-url]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const url = (btn as HTMLElement).dataset.copyUrl
      if (url) {
        navigator.clipboard.writeText(url).then(() => {
          const original = btn.textContent
          btn.textContent = 'Copied!'
          setTimeout(() => { btn.textContent = original }, 1500)
        })
      }
    })
  })
}

function bindCmdCopyButtons(): void {
  document.querySelectorAll('[data-connect-copy-cmd]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const codeEl = btn.previousElementSibling
      const cmd = codeEl?.textContent ?? ''
      if (cmd) {
        navigator.clipboard.writeText(cmd).then(() => {
          const original = btn.textContent
          btn.textContent = 'Copied!'
          setTimeout(() => { btn.textContent = original }, 1500)
        })
      }
    })
  })
}

function bindConnectSection(): void {
  document.querySelectorAll('[data-client-tab]').forEach((tab) => {
    tab.addEventListener('click', () => {
      const client = (tab as HTMLElement).dataset.clientTab as ConnectClient
      activeConnectClient = client

      // Update active tab
      document.querySelectorAll('[data-client-tab]').forEach((t) => t.classList.remove('connect-tab--active'))
      tab.classList.add('connect-tab--active')

      // Update steps and code block (targeted DOM update, no full re-render)
      const stepsEl = document.getElementById('connect-steps')
      const codeEl = document.getElementById('connect-config-code')
      const codeWrapper = document.getElementById('connect-code-wrapper')
      const hasJson = clientHasJsonConfig(client)

      if (stepsEl) stepsEl.innerHTML = getClientSteps(client)
      if (codeEl) codeEl.textContent = getClientConfig(client)

      // Show/hide JSON config block
      if (codeWrapper) {
        codeWrapper.classList.toggle('hidden', !hasJson)
      }

      // Show/hide "or add JSON config manually" divider for Claude Code
      const oldDivider = document.getElementById('connect-divider')
      if (oldDivider) oldDivider.remove()
      if (client === 'claude-code' && codeWrapper) {
        const newDivider = document.createElement('div')
        newDivider.className = 'divider'
        newDivider.id = 'connect-divider'
        newDivider.textContent = 'or add JSON config manually'
        codeWrapper.parentNode?.insertBefore(newDivider, codeWrapper)
      }

      // Rebind cmd copy buttons (CLI command / URL block)
      bindCmdCopyButtons()
    })
  })

  bindCmdCopyButtons()

  // Copy config JSON button
  document.querySelectorAll('[data-connect-copy]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const codeEl = document.getElementById('connect-config-code')
      const json = codeEl?.textContent ?? ''
      if (json) {
        navigator.clipboard.writeText(json).then(() => {
          const original = btn.textContent
          btn.textContent = 'Copied!'
          setTimeout(() => { btn.textContent = original }, 1500)
        })
      }
    })
  })
}

// Auth state listener
supabase.auth.onAuthStateChange((_event, session) => {
  if (session?.user) {
    currentUser = { id: session.user.id, email: session.user.email ?? '' }

    // Check for OAuth returnTo (consent page redirect after login)
    const hashParams = new URLSearchParams(window.location.hash.split('?')[1] || '')
    const returnTo = hashParams.get('returnTo')
    if (returnTo && returnTo.startsWith('/oauth/')) {
      // Redirect back to consent page with authorization_id preserved
      window.location.href = returnTo
      return
    }
  } else {
    currentUser = null
  }
  render()
})

// Initialize
async function init(): Promise<void> {
  const { data: { session } } = await supabase.auth.getSession()
  if (session?.user) {
    currentUser = { id: session.user.id, email: session.user.email ?? '' }
  }
  render()
}

window.addEventListener('hashchange', render)
init()
