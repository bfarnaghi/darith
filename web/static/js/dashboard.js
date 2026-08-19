/*
 * Author: Behnam <b.farnaghi@gmail.com>
 * AI-assisted implementation; manually reviewed and verified by the developer.
 */
const app = document.querySelector(".app-shell");
const panels = [...document.querySelectorAll("[data-tab-panel]")];
const tabButtons = [...document.querySelectorAll("[data-tab-target]")];
const titles = {
    overview: app.dataset.titleOverview,
    accounts: app.dataset.titleAccounts,
    transactions: app.dataset.titleTransactions,
    plans: app.dataset.titlePlans,
    categories: app.dataset.titleCategories,
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

const timelineRoot = document.querySelector("[data-timeline-root]");
const timelineDataElement = document.getElementById("forecast-timeline-data");

if (timelineRoot && timelineDataElement) {
    const timelineRows = JSON.parse(timelineDataElement.textContent || "[]");
    const slider = timelineRoot.querySelector("[data-timeline-slider]");
    const previousButton = timelineRoot.querySelector("[data-timeline-prev]");
    const nextButton = timelineRoot.querySelector("[data-timeline-next]");
    const todayButton = timelineRoot.querySelector("[data-timeline-today]");
    const eventRail = timelineRoot.querySelector("[data-timeline-event-rail]");
    const dateValue = timelineRoot.querySelector("[data-timeline-date]");
    const statusValue = timelineRoot.querySelector("[data-timeline-status]");
    const safeValue = timelineRoot.querySelector("[data-timeline-safe]");
    const balanceValue = timelineRoot.querySelector("[data-timeline-balance]");
    const incomeLeftValue = timelineRoot.querySelector("[data-timeline-income-left]");
    const expensesLeftValue = timelineRoot.querySelector("[data-timeline-expenses-left]");
    const savingsLeftValue = timelineRoot.querySelector("[data-timeline-savings-left]");
    const dailyRemainingValue = timelineRoot.querySelector("[data-timeline-daily-remaining]");
    const bufferWrap = timelineRoot.querySelector("[data-timeline-buffer-wrap]");
    const bufferValue = timelineRoot.querySelector("[data-timeline-buffer]");
    const incomeValue = timelineRoot.querySelector("[data-timeline-income]");
    const expensesValue = timelineRoot.querySelector("[data-timeline-expenses]");
    const savingsValue = timelineRoot.querySelector("[data-timeline-savings]");
    const dailyValue = timelineRoot.querySelector("[data-timeline-daily]");
    const eventsValue = timelineRoot.querySelector("[data-timeline-events]");

    function renderTimelineEvents(row) {
        eventsValue.replaceChildren();
        if (!row.events.length) {
            const empty = document.createElement("p");
            empty.className = "timeline-event-empty";
            empty.textContent = timelineRoot.dataset.noEvents;
            eventsValue.append(empty);
            return;
        }

        row.events.forEach((event) => {
            const item = document.createElement("div");
            item.className = `timeline-event-item ${event.kind}`;
            const copy = document.createElement("span");
            const dot = document.createElement("i");
            const name = document.createElement("em");
            const amount = document.createElement("strong");
            name.textContent = event.name;
            amount.textContent = event.amount;
            copy.append(dot, name);
            item.append(copy, amount);
            eventsValue.append(item);
        });
    }

    function renderTimeline(index) {
        if (!timelineRows.length) return;
        const safeIndex = Math.max(0, Math.min(index, timelineRows.length - 1));
        const row = timelineRows[safeIndex];
        slider.value = String(safeIndex);
        slider.setAttribute("aria-valuetext", `${row.dateLong}: ${row.safe}`);
        dateValue.textContent = row.dateLong;
        statusValue.textContent = row.statusLabel;
        safeValue.textContent = row.safe;
        balanceValue.textContent = row.balance;
        incomeLeftValue.textContent = row.incomeLeft;
        expensesLeftValue.textContent = row.expensesLeft;
        savingsLeftValue.textContent = row.savingsLeft;
        dailyRemainingValue.textContent = row.dailyRemaining;
        bufferValue.textContent = row.buffer;
        bufferWrap.hidden = !row.hasBuffer;
        incomeValue.textContent = row.incomeToday;
        expensesValue.textContent = row.expensesToday;
        savingsValue.textContent = row.savingsToday;
        dailyValue.textContent = row.dailyCost;
        timelineRoot.dataset.status = row.status;
        previousButton.disabled = safeIndex === 0;
        nextButton.disabled = safeIndex === timelineRows.length - 1;
        renderTimelineEvents(row);
    }

    function buildTimelineRail() {
        eventRail.replaceChildren();
        if (timelineRows.length < 2) return;
        timelineRows.forEach((row, index) => {
            const position = (index / (timelineRows.length - 1)) * 100;
            if (row.isMonthStart && index !== 0) {
                const boundary = document.createElement("span");
                boundary.className = "timeline-event-dot month-start";
                boundary.style.left = `${position}%`;
                eventRail.append(boundary);
            }
            if (!row.events.length) return;
            const marker = document.createElement("span");
            const kinds = new Set(row.events.map((event) => event.kind));
            let kind = "saving";
            if (kinds.has("income")) kind = "income";
            else if (kinds.has("expense")) kind = "expense";
            marker.className = `timeline-event-dot ${kind}`;
            marker.style.left = `${position}%`;
            eventRail.append(marker);
        });
    }

    if (timelineRows.length) {
        slider.max = String(timelineRows.length - 1);
        slider.addEventListener("input", () => renderTimeline(Number(slider.value)));
        previousButton.addEventListener("click", () => renderTimeline(Number(slider.value) - 1));
        nextButton.addEventListener("click", () => renderTimeline(Number(slider.value) + 1));
        todayButton.addEventListener("click", () => renderTimeline(0));
        buildTimelineRail();
        renderTimeline(0);
    }
}

const settingsDialog = document.getElementById("dashboard-animation-edit");
const settingsTabs = [...document.querySelectorAll("[data-settings-tab]")];
const settingsPanels = [...document.querySelectorAll("[data-settings-panel]")];

function activateSettingsTab(name) {
    const selected = settingsPanels.some((panel) => panel.dataset.settingsPanel === name) ? name : "planning";
    settingsTabs.forEach((button) => {
        const active = button.dataset.settingsTab === selected;
        button.setAttribute("aria-selected", active ? "true" : "false");
        button.tabIndex = active ? 0 : -1;
    });
    settingsPanels.forEach((panel) => { panel.hidden = panel.dataset.settingsPanel !== selected; });
}

settingsTabs.forEach((button) => {
    button.addEventListener("click", () => activateSettingsTab(button.dataset.settingsTab));
    button.addEventListener("keydown", (event) => {
        if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
        event.preventDefault();
        const direction = event.key === "ArrowRight" ? 1 : -1;
        const nextIndex = (settingsTabs.indexOf(button) + direction + settingsTabs.length) % settingsTabs.length;
        activateSettingsTab(settingsTabs[nextIndex].dataset.settingsTab);
        settingsTabs[nextIndex].focus();
    });
});
document.querySelectorAll("[data-dialog-open]").forEach((button) => {
    button.addEventListener("click", () => {
        const dialog = document.getElementById(button.dataset.dialogOpen);
        if (dialog === settingsDialog) activateSettingsTab("planning");
        dialog?.showModal();
    });
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
