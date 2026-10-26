# Live BBCom feature automation (2026-10-26)

These tools require the matching updated BBCom build, a running **main window**, and its enabled TCP mirror. Restart this MCP server after updating its source. The package/application version numbers were intentionally not changed; discover support with `bbcom_capabilities`, not a version-number comparison alone.

The server now registers **47 MCP tools**, including 21 feature tools added in `bbcom_features.py`. `bbcom_capabilities` returns the live catalog of **81 operations** with exact camelCase argument names. Existing serial/mirror/BBLog tools remain available.

| Tool | Operations |
|---|---|
| `bbcom_capabilities` | Live operation discovery |
| `bbcom_protocol_templates` / `bbcom_protocol_template` | Built-in/user templates; validate/import/export/remove JSONC |
| `bbcom_protocol_start` / `status` / `wait` / `cancel` | Real XMODEM/YMODEM engine, session-scoped progress/events and cancellation |
| `bbcom_notes` | Status/configure/add/edit/remove/clear/undo/select/save |
| `bbcom_logs` | Read paged retained rows, clear current view, replay annotated logs |
| `bbcom_log_recording` | Serial Save Log, including embedded Notes; explicit stop/save decision |
| `bbcom_binary_recording` | Raw serial recording start/stop |
| `bbcom_waveform` | Config/separators/sync, targets, actual samples, fit/range/clear, live scales |
| `bbcom_timer` / `bbcom_traffic_control` | Instance-owned floating windows and controls |
| `bbcom_adb` / `bbcom_job_status` | Device/logcat/wireless/shell/info; asynchronous bugreport and status/cancel |
| `bbcom_proxy` | com0com detection, pairs, start/stop/state/forward |
| `bbcom_rtt` | Probes/chips/J-Link devices; open with full rttConfig, close |
| `bbcom_terminal` | TCP/UDP/shell connect/status/send/resize/disconnect |
| `bbcom_commands` | Search/send loaded commands; JSON/JSONC load, JSON save |
| `bbcom_ui` / `bbcom_config_save` | Theme/language/mode/sidebar/autoscroll; full configuration snapshot |

## Examples

1. `bbcom_capabilities()` — inspect actual support and argument names.
2. `bbcom_protocol_templates()` — obtain a complete template. Default built-in IDs: `bbcom.xmodem-sum8`, `bbcom.xmodem`, `bbcom.xmodem-1k`, `bbcom.ymodem`.
3. Prepare the device using existing mirror tools and wait for its READY response.
4. `bbcom_protocol_start(direction="send", path="D:\\test\\payload.bin", template=<returned template>)`.
5. Retain `sessionId`; call `bbcom_protocol_wait(session_id=..., timeout_seconds=30)`. Timeout **does not** cancel. A superseded session is an error, never another session's success.
6. Verify device RESULT and SHA-256 independently; completed protocol state is not a file hash assertion.

XMODEM reception preserves padding unless `exact_length` is provided. YMODEM obtains length from its header. Receives require a new destination path and share BBCom's connection lease, cancellation and temporary-file safeguards.

Notes: `bbcom_logs(action="read", arguments={"limit":100})` returns stable `noteKey` values. Enable editing with `bbcom_notes("configure", {"enabled":true})`, then `add` using `key`, `text`, optional `color`. `remove` and `clear` change memory only. `save` with a new `path` produces a **single full annotated log**; omitting path commits edits to opened documents. Replay refuses unsaved conflicts. Notes output is paged (default 100, max 500); `only` config controls the actual log filter.

Waveform: `configure` takes `config`, e.g. `{"equalMark":": ","delimiter":"|","syncEnabled":true}`. `fit` applies each mounted chart's one-shot Y fit. `range` takes `chartId,xMin,xMax,yMin,yMax`; only X is synchronized. `status.liveScales` reflects mounted uPlot instances, not merely cached settings. UI visual correctness still requires visual inspection.

Timer: `bbcom_timer("control", {"action":"configure","mode":"down","countdownSecs":120})`, then `control/start`, `control/stop` or `control/reset`. Appearance comes from the owning main window. `always_on_top` takes `onTop`.

ADB export: `bbcom_adb("bugreport", {"adbPath":"...","device":"...","savePath":"...zip"})` returns `jobId` immediately. Poll `bbcom_job_status`; use ADB `bugreport_status` for device progress and `cancel_bugreport` to cancel. The latest 20 job results are retained until the window reloads.

`bbcom_ui("configure", {"mode":"serial","sideTab":"protocols","autoScroll":true})` selects the actual mode/sidebar. Theme accepts dark/light/system; language accepts en-US/zh-CN.

## CLI, same implementation

```powershell
.\.venv\Scripts\python.exe bbcom_cli.py
.\.venv\Scripts\python.exe bbcom_cli.py protocol_templates
.\.venv\Scripts\python.exe bbcom_cli.py protocol_start --args-file transfer-request.json
.\.venv\Scripts\python.exe bbcom_cli.py protocol_status --args-file session.json
```

The argument file contains the operation's argument object from capabilities. CLI stdout is JSON; errors exit 1. After installing the package, `bbcom-rpc` is the equivalent entry point. This CLI does not launch another BBCom or maintain a copy of the protocol engine.

## Errors and limits

- TCP control frames are newline-delimited and bounded at 128 KiB. Responses are bounded at 8 MiB. Use pagination.
- RPC timeout can mean an unknown outcome. Query state before retrying any mutation; no automatic mutation retries or fallback to another process occur.
- Main-window operations expire before execution if queued too long. A closed/unresponsive window is not a successful operation.
- Notes snapshot/template/config/command exports require new filenames. Unsaved edits are not silently discarded. File paths are local to the machine running BBCom.
- The integrated Save Log workflow currently targets **serial mode**. It requires serial mode selected; do not use serial flags to start ADB/terminal recordings.
- Shell, wireless, proxy and forwarding operations can affect the connected device/application. Only call when the user has authorized that task.
- Account/purchase/update/security/driver-install operations are not exposed. No arbitrary JavaScript evaluation or arbitrary Tauri command is available.
- Multiple BBCom instances: check runtime status and mirror endpoint to verify the selected process before testing; window titles alone are not identity.
- The previous independent protocol CLI's copied engine is not updated by these tools. Use this live CLI to test the actual application, including lease/UI behavior.

## Self-test

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Tests include actual MCP stdio initialization/tool calls, operation mapping, bounded waits, session-specific cancel, error propagation, and fragmented TCP responses mixed with log traffic.
