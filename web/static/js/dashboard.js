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
