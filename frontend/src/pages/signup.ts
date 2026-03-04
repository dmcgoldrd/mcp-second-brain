export function renderSignup(): string {
  return `
    <div class="header">
      <h1>MCP <span class="accent">Brain</span></h1>
      <p class="text-muted">Create your AI memory account</p>
    </div>

    <div class="card">
      <form id="signup-form">
        <div class="form-group">
          <label for="signup-email">Email</label>
          <input type="email" id="signup-email" placeholder="you@example.com" required />
        </div>
        <div class="form-group">
          <label for="signup-password">Password</label>
          <input type="password" id="signup-password" placeholder="At least 6 characters" required minlength="6" />
        </div>
        <div class="form-group">
          <label for="signup-confirm">Confirm Password</label>
          <input type="password" id="signup-confirm" placeholder="Confirm your password" required minlength="6" />
        </div>
        <div id="signup-error" class="error-msg"></div>
        <div id="signup-success" class="success-msg"></div>
        <button type="submit" class="btn btn-primary mt-2">Create Account</button>
      </form>
    </div>

    <p class="text-center text-muted mt-2">
      Already have an account? <a href="#/login" class="link">Sign in</a>
    </p>
  `
}
