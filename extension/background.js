/* LoopBridge background script.
 *
 * Adds a "Send selected text to LoopBridge" context-menu item. Only the
 * user's explicit selection is read (provided by the menus API as
 * info.selectionText) — never the page, history, cookies, or credentials.
 * The text is forwarded as plain JSON to the native host together with a
 * generated request ID and the source tab's numeric ID (the minimum needed
 * to route the response back). Tab IDs are per-session integers: they are
 * invalid once the tab closes or Firefox restarts. Nothing is executed,
 * submitted, or stored by the extension.
 */

"use strict";

const NATIVE_HOST = "com.loopbridge.bridge";
const MAX_SELECTION_CHARS = 32000;

browser.menus.create({
  id: "loopbridge-send-selection",
  title: "Send selected text to LoopBridge",
  contexts: ["selection"],
});

browser.menus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId !== "loopbridge-send-selection") {
    return;
  }
  const text = info.selectionText;
  if (typeof text !== "string" || text.trim().length === 0) {
    console.warn("LoopBridge: selection is empty, nothing sent.");
    return;
  }
  if (text.length > MAX_SELECTION_CHARS) {
    console.warn(
      `LoopBridge: selection too large (${text.length} chars, limit ${MAX_SELECTION_CHARS}), nothing sent.`
    );
    return;
  }
  const message = {
    type: "loopbridge.selection",
    text,
    requestId:
      typeof crypto.randomUUID === "function"
        ? crypto.randomUUID().replace(/-/g, "")
        : String(Date.now()),
  };
  if (tab && Number.isInteger(tab.id) && tab.id >= 0) {
    message.tabId = tab.id;
  } else {
    console.warn("LoopBridge: source tab unknown; response cannot be routed back.");
  }
  try {
    const response = await browser.runtime.sendNativeMessage(NATIVE_HOST, message);
    if (!response || response.ok !== true) {
      console.warn("LoopBridge: host rejected the text:", response);
    }
  } catch (error) {
    console.warn("LoopBridge: native host unreachable:", error);
  }
});
