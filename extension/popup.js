/* LoopBridge popup: pull a queued OpenCode response for the current tab.
 *
 * Pull-based by design — no polling, no page access. The popup asks the
 * native host for the oldest undelivered response addressed to THIS tab,
 * displays it in an extension-owned textarea for manual copying, then
 * acknowledges delivery exactly once per request ID (redeliveries are
 * deduped). A response for another tab is never shown here.
 */

"use strict";

const NATIVE_HOST = "com.loopbridge.bridge";

const statusEl = document.getElementById("status");
const resultEl = document.getElementById("result");
const fetchBtn = document.getElementById("fetch");
const copyBtn = document.getElementById("copy");
const deliveredIds = new Set();

function setStatus(text) {
  statusEl.textContent = text;
}

async function currentTabId() {
  const tabs = await browser.tabs.query({ active: true, currentWindow: true });
  if (!tabs || tabs.length === 0 || !Number.isInteger(tabs[0].id)) {
    throw new Error("cannot identify the current tab");
  }
  return tabs[0].id;
}

fetchBtn.addEventListener("click", async () => {
  setStatus("Fetching…");
  copyBtn.disabled = true;
  let tabId;
  try {
    tabId = await currentTabId();
  } catch (error) {
    setStatus(`Error: ${error.message}.`);
    return;
  }
  let reply;
  try {
    reply = await browser.runtime.sendNativeMessage(NATIVE_HOST, {
      type: "loopbridge.fetch_result",
      tabId,
    });
  } catch (error) {
    setStatus(`Native host unreachable: ${error}. Is the desktop app set up?`);
    return;
  }
  if (!reply || reply.ok !== true) {
    setStatus(`Error: ${(reply && reply.error) || "bad host reply"}.`);
    return;
  }
  const response = reply.response;
  if (!response) {
    const extra =
      reply.other_pending > 0
        ? ` ${reply.other_pending} result(s) are waiting for other tabs — open the originating tab and fetch there. (Tab IDs are invalid once a tab closes or Firefox restarts.)`
        : "";
    setStatus(`No LoopBridge result for this tab yet.${extra}`);
    return;
  }
  if (response.tabId !== tabId) {
    setStatus("Error: host returned a response for a different tab; refusing to display it.");
    return;
  }
  if (deliveredIds.has(response.requestId)) {
    setStatus("Duplicate delivery ignored (already shown).");
    return;
  }
  resultEl.value = response.text;
  copyBtn.disabled = false;
  setStatus("Result fetched. Copy it, then paste into the chat manually.");
  try {
    const ack = await browser.runtime.sendNativeMessage(NATIVE_HOST, {
      type: "loopbridge.ack_delivery",
      requestId: response.requestId,
    });
    if (ack && ack.ok === true) {
      deliveredIds.add(response.requestId);
    } else {
      setStatus("Result shown, but delivery could not be acknowledged; it may be offered again.");
    }
  } catch (error) {
    setStatus("Result shown, but delivery could not be acknowledged; it may be offered again.");
  }
});

copyBtn.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(resultEl.value);
    setStatus("Copied. Paste into the chat manually.");
  } catch (error) {
    resultEl.select();
    try {
      if (document.execCommand("copy")) {
        setStatus("Copied. Paste into the chat manually.");
      } else {
        setStatus("Copy failed; select the text manually (Ctrl+C).");
      }
    } catch (fallbackError) {
      setStatus("Copy failed; select the text manually (Ctrl+C).");
    }
  }
});
