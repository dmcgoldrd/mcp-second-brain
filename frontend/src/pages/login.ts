export function renderLogin(): string {
  return `
    <div class="header">
      <h1>MCP <span class="accent">Brain</span></h1>
      <p class="text-muted">Sign in to your AI memory</p>
    </div>

    <div class="card">
      <form id="login-form">
        <div class="form-group">
          <label for="login-email">Email</label>
          <input type="email" id="login-email" placeholder="you@example.com" required />
        </div>
        <div class="form-group">
          <label for="login-password">Password</label>
          <input type="password" id="login-password" placeholder="Your password" required />
        </div>
        <div id="login-error" class="error-msg"></div>
        <button type="submit" class="btn btn-primary mt-2">Sign In</button>
      </form>

      <div class="divider">or</div>

      <button id="google-login-btn" class="btn btn-outline">
        Sign in with Google
      </button>
    </div>

    <p class="text-center text-muted mt-2">
      Don't have an account? <a href="#/signup" class="link">Sign up</a>
    </p>
  `
}
