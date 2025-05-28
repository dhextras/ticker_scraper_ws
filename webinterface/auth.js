class Auth {
  constructor() {
    this.token = localStorage.getItem("auth_token");
  }

  async login(username, password) {
    try {
      const response = await fetch("/api/login", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ username, password }),
      });

      const result = await response.json();

      if (response.ok && result.success) {
        this.token = result.token;
        localStorage.setItem("auth_token", this.token);
        return { success: true };
      } else {
        return { success: false, error: result.error || "Login failed" };
      }
    } catch (error) {
      return { success: false, error: "Network error" };
    }
  }

  async verifyToken() {
    if (!this.token) return false;

    try {
      const response = await fetch("/api/verify", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${this.token}`,
        },
      });

      const result = await response.json();
      return response.ok && result.valid;
    } catch (error) {
      return false;
    }
  }

  logout() {
    this.token = null;
    localStorage.removeItem("auth_token");
    this.showLogin();
  }

  getToken() {
    return this.token;
  }

  showLogin() {
    document.getElementById("login-container").style.display = "flex";
    document.getElementById("app-container").style.display = "none";
    document.body.style.display = "flex";
    document.body.style.justifyContent = "center";
    document.body.style.alignItems = "center";
    document.body.style.minHeight = "100vh";
  }

  showApp() {
    document.getElementById("login-container").style.display = "none";
    document.getElementById("app-container").style.display = "block";
    document.body.style.display = "block";
    document.body.style.justifyContent = "initial";
    document.body.style.alignItems = "initial";
    document.body.style.minHeight = "initial";
  }
}

const auth = new Auth();

window.addEventListener("load", async () => {
  const loginForm = document.getElementById("login-form");
  const loginError = document.getElementById("login-error");
  const logoutBtn = document.getElementById("logout-btn");

  const isValid = await auth.verifyToken();
  if (isValid) {
    auth.showApp();
    if (window.initApp) {
      window.initApp();
    }
  } else {
    auth.showLogin();
  }

  // Handle login form
  loginForm.addEventListener("submit", async (e) => {
    e.preventDefault();

    const username = document.getElementById("username").value;
    const password = document.getElementById("password").value;
    const loginBtn = document.getElementById("login-btn");

    loginBtn.disabled = true;
    loginBtn.textContent = "Logging in...";
    loginError.style.display = "none";

    const result = await auth.login(username, password);

    if (result.success) {
      auth.showApp();
      if (window.initApp) {
        window.initApp();
      }
    } else {
      loginError.textContent = result.error;
      loginError.style.display = "block";
    }

    loginBtn.disabled = false;
    loginBtn.textContent = "Login";
  });

  // Handle logout
  logoutBtn.addEventListener("click", () => {
    auth.logout();
  });
});
