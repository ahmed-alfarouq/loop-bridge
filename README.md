# LoopBridge (minimal, v0.1.0)

Minimal Windows desktop app (Python + PySide6) that runs **one isolated
OpenCode request** and shows its response, with a Firefox side-channel:
select chat text in Firefox to send it in, run it explicitly, and pull the
result back into an extension popup for manual copying. First runnable slice
— no multi-agent support, no persistent orchestration, no automatic
insertion/submission yet.

## Prerequisites

- Windows 10/11 x64
- Python 3.11+ with PySide6 (`pip install PySide6`)
- OpenCode Desktop with its bundled CLI
  (`%LOCALAPPDATA%\Programs\@opencodedesktop\resources\opencode-cli.exe`),
  override with `LOOPBRIDGE_OPENCODE_CLI` if installed elsewhere
- `pytest` to run the test suite

## Run

```powershell
cd LoopBridge  # wherever you cloned https://github.com/ahmed-alfarouq/loop-bridge
$env:PYTHONPATH = "src"
python -m loopbridge
```

The window shows an OpenCode connection indicator, a response area, and a
**Run test prompt** button. The button executes one harmless request
(`Reply with exactly this single line: LOOPBRIDGE-PROBE-OK. …`) in a fresh
empty temp directory using `opencode run --standalone --format json` and
displays the extracted text plus the session ID and exit code. Errors are
shown in red — never silently treated as success.

## Tests

```powershell
$env:PYTHONPATH = "src"
python -m pytest
```

Unit tests mock `subprocess` and consume no model quota. Host-protocol
tests execute the real `hosts/loopbridge_host.py` with an isolated inbox.

## Firefox selection capture (browser → desktop)

The `extension/` directory holds a minimal Manifest V2 WebExtension. It adds
a **Send selected text to LoopBridge** context-menu entry that forwards
*only the explicit selection* (max 32,000 chars) to the native host.
Permissions are limited to `menus` + `nativeMessaging` + `clipboardWrite`
(for the popup Copy button) — no host access, no page reads, no
history/cookies/attachments.

The native host (`hosts/loopbridge_host.py`, stdlib only) validates one
framed JSON message and drops it into `%LOCALAPPDATA%\LoopBridge\inbox\`.
It can never launch OpenCode, execute commands, or open sockets. The desktop
app watches the inbox, shows new text under “Received from Firefox”, and
runs it **only** when you click **Run in OpenCode**.

### One-time setup (explicit, per-user)

```powershell
cd LoopBridge  # wherever you cloned the repo
python scripts/install_native_host.py          # dry-run: prints planned actions
python scripts/install_native_host.py --apply  # writes HKCU key + manifest + launcher
```

`--apply` writes only `HKCU\Software\Mozilla\NativeMessagingHosts\...`
plus files under `%LOCALAPPDATA%\LoopBridge\host\`. `--status` checks
registration read-only; `--uninstall` removes the key.

Then in Firefox: `about:debugging → This Firefox → Load Temporary Add-on →
extension/manifest.json` (temporary; lasts until Firefox restarts).

### Manual verification

1. Launch LoopBridge (`python -m loopbridge`) and confirm the inbox line.
2. On any AI chat page, select a sentence → right-click →
   **Send selected text to LoopBridge**.
3. The desktop app shows the text and enables **Run in OpenCode** (nothing
   executes automatically). Click it to run; the response appears as usual.
4. Empty/oversize selections are refused by the extension (see Browser
   Console, `Ctrl+Shift+J`); malformed inbox files are ignored with a
   visible error and never executed.

## Returning a result to Firefox (explicit pull)

After a run that started from Firefox-selected text succeeds, the
**Send result to Firefox** button enables. Clicking it queues the response
for the originating tab — nothing is inserted or submitted anywhere.

Fetch it from the browser: click the LoopBridge toolbar button in the
**originating tab**, then **Fetch result for this tab**. The response
appears in the extension popup for manual copying (Copy button included).
Fetching for any other tab reports “no result” plus how many results wait
elsewhere; closing the tab strands its queued response (tab IDs die with
the tab) — it stays visible in the desktop app.

Message contract (all directions validated, text caps enforced):

- ext→host `loopbridge.selection {text, requestId, tabId?}`
- ext→host `loopbridge.fetch_result {tabId}` →
  `{ok, response: {requestId, tabId, text, sessionId} | null, other_pending}`
- ext→host `loopbridge.ack_delivery {requestId}` → marks delivered
  (redeliveries deduped by the popup; duplicates reported, never applied
  twice).

## Uninstalling the native host

```powershell
python scripts/install_native_host.py --uninstall  # removes the HKCU registry key only
```

What it changes: only `HKCU\Software\Mozilla\NativeMessagingHosts\...`
is removed. Left behind for your review: `%LOCALAPPDATA%\LoopBridge\host\`
(manifest, launcher, host copy) and `%LOCALAPPDATA%\LoopBridge\{inbox,outbox}\`
(received selections and queued results) — delete those folders manually if
wanted. Remove the temporary extension via
`about:debugging → This Firefox → Remove`. Nothing else on the system is
touched; OpenCode settings and sessions are never modified.

## Current limitations

- Supports the verified happy path only (`step_start` + `text` NDJSON events
  from OpenCode v2.0.29); unknown, malformed, or incomplete output fails
  visibly instead of guessing.
- No automatic retries: a timed-out or failed request may already have
  reached the model — reconcile the shown session ID before resending.
- Never passes `--auto`, file attachments, or project contents to the model.
  Each run uses a fresh empty temp dir as its working directory.
- Each click creates a new OpenCode session (billable/quota-relevant).
- Firefox path is selection-only on the way in and popup-copy on the way
  out: no DOM extraction, no auto-insert, no auto-submit, no response
  scraping. The temporary add-on install does not survive Firefox restarts
  (packaging/signing is future work).
- Delivery is pull-based (no polling): the popup fetches on click, and the
  host marks delivered only on explicit ack. No exactly-once claim across
  crashes — at-most-once per ack, redeliveries deduped.
- No automatic composer insertion or submission, session reuse/recovery UI,
  settings, or multi-agent adapters yet.
