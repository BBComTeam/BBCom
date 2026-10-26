"""Live feature tools. All operations target the running BBCom mirror RPC.

No secondary process, duplicated transfer engine, or silent CLI fallback.
"""
import json
import time
from typing import Any, Literal


def register(mcp, rpc, format_result):
    def call(command: str, arguments: dict | None = None) -> str:
        return format_result(rpc(command, arguments or {}, timeout_s=35))

    @mcp.tool()
    def bbcom_capabilities() -> str:
        """Discover live operation names, routes and argument names/types. Requires updated BBCom and mirror enabled. Use before feature calls; unavailable operations return errors, never simulated success."""
        return call('automation_capabilities')

    @mcp.tool()
    def bbcom_protocol_templates() -> str:
        """List built-in and user templates from the running window. Export any returned template as JSONC; import via bbcom_protocol_template."""
        return call('protocol_templates')

    @mcp.tool()
    def bbcom_protocol_template(action: Literal['validate', 'import', 'remove', 'export'], content: str = '', template_id: str = '', path: str = '') -> str:
        """Validate JSONC, import a custom template into the live UI library, or remove a custom template. Built-ins cannot be removed; duplicate IDs are rejected."""
        if action == 'export':
            return call('protocol_template_export', {'id': template_id, 'path': path})
        if action == 'remove':
            return call('protocol_template_remove', {'id': template_id})
        return call('protocol_validate_template' if action == 'validate' else 'protocol_template_import', {'content': content})

    @mcp.tool()
    def bbcom_protocol_start(direction: Literal['send', 'receive'], path: str, template: dict[str, Any], exact_length: int | None = None) -> str:
        """Start real GUI-engine X/YMODEM transfer on connected serial port, exclusively reserving raw bytes. Nonblocking: retain sessionId and use status/wait/cancel. Send path must exist; receive path must be NEW. XMODEM receive retains padding unless exact_length is supplied. YMODEM uses header length. Start device's matching transfer first. No automatic firmware commands."""
        return call('protocol_start', {'direction': direction, 'path': path, 'template': template, 'exactLength': exact_length})

    @mcp.tool()
    def bbcom_protocol_status(session_id: str = '') -> str:
        """Read current transfer progress and last 100 wire events. Providing session_id rejects a superseded session instead of returning another transfer's result."""
        return call('protocol_status', {'sessionId': session_id} if session_id else {})

    @mcp.tool()
    def bbcom_protocol_cancel(session_id: str) -> str:
        """Request cancellation of exactly this active transfer; poll status until inactive before sending serial commands. Partial receive files are cleaned up by BBCom."""
        return call('protocol_cancel', {'sessionId': session_id})

    @mcp.tool()
    def bbcom_protocol_wait(session_id: str, timeout_seconds: float = 30) -> str:
        """Wait at most 60 seconds for one transfer. Timeout returns still-active progress and does NOT cancel or imply completion. A superseded session is an error."""
        if not session_id or not 0 < timeout_seconds <= 60:
            return json.dumps({'type': 'error', 'message': 'session_id required; timeout_seconds must be in (0, 60]'})
        deadline = time.monotonic() + timeout_seconds
        while True:
            response = rpc('protocol_status', {'sessionId': session_id}, timeout_s=max(.01, min(10, deadline - time.monotonic())))
            envelope = response.get('rpc', {})
            if not envelope.get('ok') or not envelope.get('result', {}).get('active'):
                return format_result(response)
            if time.monotonic() >= deadline:
                result = json.loads(format_result(response))
                result['waitTimedOut'] = True
                return json.dumps(result, ensure_ascii=False)
            time.sleep(min(.25, max(0, deadline - time.monotonic())))

    @mcp.tool()
    def bbcom_notes(action: Literal['status', 'configure', 'add', 'edit', 'remove', 'clear', 'undo', 'select', 'save'], arguments: dict[str, Any] | None = None) -> str:
        """Operate actual Notes UI. Discover arguments with capabilities. Add uses stable noteKey from bbcom_logs(read); editing requires configure(enabled=true). Remove/clear modify memory only; save commits. save(path=NEW .txt) snapshots full annotated log; omitted path saves opened documents. No automatic overwrite/replay conflict discard."""
        return call('notes_' + action, arguments)

    @mcp.tool()
    def bbcom_logs(action: Literal['read', 'clear', 'replay'], arguments: dict[str, Any] | None = None) -> str:
        """Read paged actual log rows (offset/limit<=500/source), clear current log view, or replay(path,source). Replay restores embedded Notes and refuses unsaved conflicts. Stable noteKey identifies a row; indices can change as buffer fills."""
        return call('logs_' + action, arguments)

    @mcp.tool()
    def bbcom_waveform(action: Literal['status', 'configure', 'target_add', 'target_update', 'target_remove', 'data', 'fit', 'range', 'clear'], arguments: dict[str, Any] | None = None) -> str:
        """Inspect/configure live waveform, custom separators, sync, targets, data and scales. Use capabilities for args. fit is one-shot Y fit; range syncs only X. Chart operations require mounted waveform charts; no synthetic samples are injected."""
        return call('waveform_' + action, arguments)

    @mcp.tool()
    def bbcom_adb(action: Literal['list_devices', 'start_logcat', 'stop_logcat', 'clear_logcat', 'pair', 'connect', 'status', 'shell_command', 'bugreport', 'cancel_bugreport', 'bugreport_status', 'validate_path', 'device_info'], arguments: dict[str, Any] | None = None) -> str:
        """ADB tools using the running BBCom backend. Discover exact camelCase args with capabilities. Shell/clear/pair/connect modify the device. bugreport returns jobId immediately: poll bbcom_job_status for completion, bugreport_status for device progress, cancel_bugreport to cancel."""
        return call('adb_' + action, arguments)

    @mcp.tool()
    def bbcom_job_status(job_id: str) -> str:
        """Poll an asynchronous ADB export started via MCP. Keeps the latest 20 jobs until window reload; never treats an unknown job as completed."""
        return call('automation_job_status', {'jobId': job_id})

    @mcp.tool()
    def bbcom_proxy(action: Literal['check_com0com', 'detect_pairs', 'get_state', 'start', 'stop', 'forward_to_app'], arguments: dict[str, Any] | None = None) -> str:
        """Control actual Com Proxy. start requires connected real serial port, virtualPort and baudRate; cannot coexist with protocol transfer. No virtual driver installation is performed."""
        return call('proxy_' + action, arguments)

    @mcp.tool()
    def bbcom_timer(action: Literal['open', 'close', 'status', 'is_open', 'control', 'always_on_top'], arguments: dict[str, Any] | None = None) -> str:
        """Timer for this BBCom instance only. control arguments: action=start/stop/reset/configure, mode=up/down, countdownSecs, showMs. status returns owner appearance and timerState; always_on_top takes onTop boolean."""
        return call({'open': 'create_timer_window', 'close': 'close_timer_window', 'status': 'get_floating_window_context', 'is_open': 'is_timer_window_open', 'control': 'timer_control', 'always_on_top': 'set_timer_window_always_on_top'}[action], arguments)

    @mcp.tool()
    def bbcom_traffic_control(action: Literal['open', 'close', 'snapshot', 'deltas', 'baseline', 'clear']) -> str:
        """Open/close this instance's traffic window, inspect counters, set baseline or reset counters."""
        return call({'open': 'create_traffic_window', 'close': 'close_traffic_window', 'snapshot': 'traffic_get', 'deltas': 'traffic_deltas', 'baseline': 'traffic_set_baseline', 'clear': 'traffic_clear'}[action])

    @mcp.tool()
    def bbcom_rtt(action: Literal['probes', 'chips', 'jlink_devices', 'open', 'close'], arguments: dict[str, Any] | None = None) -> str:
        """Enumerate and connect RTT using current backend. open requires rttConfig, autoBreakMs and optional encoding; config exposes backend, chip, exact/range search options. Inspect get_config via bbcom_rpc/capabilities first."""
        return call({'probes': 'list_probes', 'chips': 'list_chips', 'jlink_devices': 'list_jlink_devices_cmd', 'open': 'open_rtt', 'close': 'close_port'}[action], arguments)

    @mcp.tool()
    def bbcom_terminal(action: Literal['get_status', 'connect', 'disconnect', 'send', 'send_bytes', 'resize'], arguments: dict[str, Any] | None = None) -> str:
        """TCP/UDP/shell terminal backend operations. Discover connection and data arguments with capabilities. Disconnecting the mirror used for RPC can interrupt the response; inspect status before retry."""
        return call('terminal_' + action, arguments)

    @mcp.tool()
    def bbcom_commands(action: Literal['list', 'send', 'load', 'save'], arguments: dict[str, Any] | None = None) -> str:
        """Search loaded command set (list/search) and send by stable id through the current serial/terminal/ADB mode. Honors HEX and line-ending settings."""
        return call('commands_' + action, arguments)

    @mcp.tool()
    def bbcom_log_recording(action: Literal['start', 'stop', 'status'], path: str = '', include_notes: bool = False, save_notes: bool | None = None) -> str:
        """Serial Save Log workflow, including live Notes in a single annotated file. start requires a NEW path. stop with unsaved Notes requires save_notes=true to commit or false to keep edits only in memory. Does not replace Notes Save; use bbcom_notes(save) for later explicit commits."""
        args = {'action': action}
        if action == 'start':
            args.update(path=path, includeNotes=include_notes)
        if save_notes is not None:
            args['saveNotes'] = save_notes
        return call('logs_recording', args)

    @mcp.tool()
    def bbcom_config_save(path: str) -> str:
        """Snapshot actual UI configuration, including waveform settings, to a NEW JSON file; never overwrite an existing file."""
        return call('config_save', {'path': path})

    @mcp.tool()
    def bbcom_ui(action: Literal['status', 'configure'], arguments: dict[str, Any] | None = None) -> str:
        """Inspect live UI or set theme dark/light/system and language en-US/zh-CN. Changes use actual settings store and propagate to floating windows."""
        return call('ui_' + action, arguments)

    @mcp.tool()
    def bbcom_binary_recording(action: Literal['start', 'stop'], arguments: dict[str, Any] | None = None) -> str:
        """Start/stop raw byte recording using BBCom. Start args: path and optional source. This is binary data, not an annotated log or protocol transfer."""
        return call(action + '_binary_recording', arguments)
