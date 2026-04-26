function showToast(message, type = "success") {
  let toast = document.getElementById("toast");
  if (!toast) {
    toast = document.createElement("div");
    toast.id = "toast";
    toast.className = "toast";
    document.body.appendChild(toast);
  }
  toast.textContent = message;
  toast.className = `toast ${type} show`;
  setTimeout(() => toast.classList.remove("show"), 3500);
}

async function refreshBalance() {
  const el = document.getElementById("balance-display");
  const addrEl = document.getElementById("wallet-address");
  if (!el) return;

  try {
    const res = await fetch("/api/v1/balance");
    const data = await res.json();
    if (data.success) {
      el.textContent = `${parseFloat(data.balance).toFixed(2)} USDC`;
      if (addrEl && data.wallet_address) {
        const addr = data.wallet_address;
        addrEl.textContent = addr.slice(0, 6) + "…" + addr.slice(-4);
        addrEl.title = addr;
      }
    } else {
      el.textContent = "—";
    }
  } catch {
    el.textContent = "—";
  }
}

async function submitMandate(event) {
  event.preventDefault();
  const form = event.target;
  const btn = form.querySelector("button[type=submit]");
  btn.disabled = true;

  const payload = {
    locus_auth_token: form.locus_auth_token.value.trim(),
    max_task_budget: parseFloat(form.max_task_budget.value),
    daily_limit: parseFloat(form.daily_limit.value),
    required_assessor_score: parseFloat(form.required_assessor_score.value),
  };

  try {
    const res = await fetch("/api/v1/mandate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (data.success) {
      showToast(`Wallet connected — ${parseFloat(data.balance).toFixed(2)} USDC available`, "success");
      setTimeout(() => (window.location.href = "/"), 1500);
    } else {
      showToast(data.error || "Failed to save mandate", "error");
    }
  } catch {
    showToast("Network error — could not reach server", "error");
  } finally {
    btn.disabled = false;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const mandateForm = document.getElementById("mandate-form");
  if (mandateForm) mandateForm.addEventListener("submit", submitMandate);

  if (document.getElementById("balance-display")) {
    refreshBalance();
    setInterval(refreshBalance, 30000);
  }
});
