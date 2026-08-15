/*
 * Author: Behnam <b.farnaghi@gmail.com>
 * AI-assisted implementation; manually reviewed and verified by the developer.
 */
const app = document.querySelector(".app-shell");
const panels = [...document.querySelectorAll("[data-tab-panel]")];
const tabButtons = [...document.querySelectorAll("[data-tab-target]")];
const titles = {
    overview: "Overview",
    accounts: "Accounts",
    transactions: "Transactions",
    plans: "Monthly plans",
    categories: "Categories",
};

function activateTab(name, updateUrl = true) {
    const selected = titles[name] ? name : "overview";
    panels.forEach((panel) => { panel.hidden = panel.dataset.tabPanel !== selected; });
    tabButtons.forEach((button) => {
        button.classList.toggle("active", button.dataset.tabTarget === selected);
        button.setAttribute("aria-current", button.dataset.tabTarget === selected ? "page" : "false");
    });
    document.querySelector("[data-page-title]").textContent = titles[selected];
    if (updateUrl) history.replaceState({}, "", `?tab=${selected}`);
    window.scrollTo({ top: 0, behavior: "smooth" });
}

tabButtons.forEach((button) => button.addEventListener("click", () => activateTab(button.dataset.tabTarget)));
activateTab(app.dataset.activeTab, false);

document.querySelectorAll("[data-dialog-open]").forEach((button) => {
    button.addEventListener("click", () => document.getElementById(button.dataset.dialogOpen)?.showModal());
});
document.querySelectorAll("[data-dialog-close]").forEach((button) => {
    button.addEventListener("click", () => button.closest("dialog").close());
});
document.querySelectorAll("dialog").forEach((dialog) => {
    dialog.addEventListener("click", (event) => {
        if (event.target === dialog) dialog.close();
    });
});
document.querySelectorAll("[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (event) => {
        if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    });
});
document.querySelectorAll("[data-confirm-submit]").forEach((button) => {
    button.addEventListener("click", (event) => {
        if (!window.confirm(button.dataset.confirmSubmit)) event.preventDefault();
    });
});

const lockTimeoutSeconds = Number(app.dataset.lockTimeoutSeconds || 0);
if (lockTimeoutSeconds > 0) {
    let idleTimer;
    let locking = false;
    let lastInteraction = Date.now();
    let lastHeartbeat = 0;
    const csrf = document.querySelector("input[name='csrfmiddlewaretoken']")?.value || "";

    async function lockDarith() {
        if (locking) return;
        locking = true;
        app.classList.add("client-locked");
        try {
            const response = await fetch(app.dataset.lockUrl, {
                method: "POST",
                credentials: "same-origin",
                headers: {"X-CSRFToken": csrf},
                keepalive: true,
            });
            const payload = await response.json();
            window.location.assign(payload.redirect || app.dataset.lockedUrl);
        } catch (error) {
            locking = false;
            window.setTimeout(lockDarith, 5000);
        }
    }

    async function heartbeat() {
        const now = Date.now();
        if (now - lastHeartbeat < 30000 || locking) return;
        lastHeartbeat = now;
        const response = await fetch(app.dataset.activityUrl, {
            method: "POST",
            credentials: "same-origin",
            headers: {"X-CSRFToken": csrf},
            keepalive: true,
        });
        if (response.status === 423) window.location.assign(app.dataset.lockedUrl);
    }

    function scheduleLock() {
        if (locking) return;
        lastInteraction = Date.now();
        window.clearTimeout(idleTimer);
        idleTimer = window.setTimeout(lockDarith, lockTimeoutSeconds * 1000);
        heartbeat().catch(() => {});
    }

    ["pointerdown", "keydown", "touchstart", "scroll"].forEach((eventName) => {
        document.addEventListener(eventName, scheduleLock, {passive: true});
    });
    document.addEventListener("visibilitychange", () => {
        if (document.visibilityState !== "visible") return;
        if (Date.now() - lastInteraction >= lockTimeoutSeconds * 1000) lockDarith();
    });
    idleTimer = window.setTimeout(lockDarith, lockTimeoutSeconds * 1000);
}
