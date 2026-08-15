/*
 * Author: Behnam <b.farnaghi@gmail.com>
 * AI-assisted implementation; manually reviewed and verified by the developer.
 */
(function () {
    const root = document.querySelector("[data-passkey-options-url]");
    const registerButton = document.querySelector("[data-passkey-register]");
    const authenticateButton = document.querySelector("[data-passkey-authenticate]");
    const message = document.querySelector("[data-passkey-message]");
    if (!root || (!registerButton && !authenticateButton)) return;

    const supported = window.isSecureContext && "PublicKeyCredential" in window;
    if (!supported) {
        if (registerButton) registerButton.hidden = true;
        if (authenticateButton) authenticateButton.hidden = true;
        if (message) message.textContent = "Passkeys need HTTPS and a supported browser.";
        return;
    }

    function csrfToken() {
        return document.querySelector("input[name='csrfmiddlewaretoken']")?.value || "";
    }

    function base64urlToBytes(value) {
        const padding = "=".repeat((4 - (value.length % 4)) % 4);
        const base64 = (value + padding).replace(/-/g, "+").replace(/_/g, "/");
        const binary = window.atob(base64);
        return Uint8Array.from(binary, (character) => character.charCodeAt(0));
    }

    function bytesToBase64url(value) {
        if (!value) return null;
        const bytes = new Uint8Array(value);
        let binary = "";
        bytes.forEach((byte) => { binary += String.fromCharCode(byte); });
        return window.btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    }

    function browserOptions(options) {
        options.challenge = base64urlToBytes(options.challenge);
        if (options.user?.id) options.user.id = base64urlToBytes(options.user.id);
        ["excludeCredentials", "allowCredentials"].forEach((key) => {
            if (options[key]) {
                options[key] = options[key].map((item) => ({
                    ...item,
                    id: base64urlToBytes(item.id),
                }));
            }
        });
        return options;
    }

    function credentialPayload(credential) {
        const response = {
            clientDataJSON: bytesToBase64url(credential.response.clientDataJSON),
        };
        if (credential.response.attestationObject) {
            response.attestationObject = bytesToBase64url(credential.response.attestationObject);
            response.transports = credential.response.getTransports?.() || [];
        } else {
            response.authenticatorData = bytesToBase64url(credential.response.authenticatorData);
            response.signature = bytesToBase64url(credential.response.signature);
            response.userHandle = bytesToBase64url(credential.response.userHandle);
        }
        return {
            id: credential.id,
            rawId: bytesToBase64url(credential.rawId),
            response,
            type: credential.type,
            authenticatorAttachment: credential.authenticatorAttachment,
            clientExtensionResults: credential.getClientExtensionResults(),
        };
    }

    async function post(url, body = {}) {
        const response = await fetch(url, {
            method: "POST",
            credentials: "same-origin",
            headers: {"Content-Type": "application/json", "X-CSRFToken": csrfToken()},
            body: JSON.stringify(body),
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || "The security request failed.");
        return payload;
    }

    async function run(button, mode) {
        button.disabled = true;
        if (message) message.textContent = mode === "register" ? "Waiting for your device..." : "Choose your passkey...";
        try {
            const options = browserOptions(await post(root.dataset.passkeyOptionsUrl));
            const credential = mode === "register"
                ? await navigator.credentials.create({publicKey: options})
                : await navigator.credentials.get({publicKey: options});
            const responseBody = mode === "register"
                ? {
                    credential: credentialPayload(credential),
                    name: document.getElementById("passkey-name")?.value || "My passkey",
                }
                : credentialPayload(credential);
            const result = await post(root.dataset.passkeyVerifyUrl, responseBody);
            if (message) message.textContent = mode === "register" ? "Passkey added." : "Unlocked.";
            window.location.assign(result.redirect || window.location.href);
        } catch (error) {
            if (message) message.textContent = error.name === "NotAllowedError"
                ? "Passkey request canceled."
                : error.message;
            button.disabled = false;
        }
    }

    registerButton?.addEventListener("click", () => run(registerButton, "register"));
    authenticateButton?.addEventListener("click", () => run(authenticateButton, "authenticate"));
})();
