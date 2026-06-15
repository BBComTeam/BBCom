#!/usr/bin/env python3
"""
BBCom MCP Server - Model Context Protocol server for BBCom serial communication tool.

Provides LLMs with the ability to:
- Query BBCom mirror status and serial configuration
- Read real-time serial data via mirror TCP connection
- Send commands to serial devices via mirror TCP connection
- Send commands AND capture responses atomically (avoids missing responses)
- Read until a specific pattern is matched (e.g. HARDFAULT, FATAL ERROR)
- Send command and read until a specific pattern appears in response
- Monitor serial data for pattern matches with minimal data transfer
- Control serial port settings

Usage:
  python bbcom_mcp_server.py

Or configure in Claude Desktop / Cursor / CodeBuddy:
  {
    "mcpServers": {
      "bbcom": {
        "type": "stdio",
        "command": "python",
        "args": ["path/to/bbcom_mcp_server.py"]
      }
    }
  }

Requirements:
  - mcp package: pip install mcp
  - BBCom must be running for most operations
"""

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

# BBCom executable name
BBCOM_EXE = "bbcom.exe" if sys.platform == "win32" else "bbcom"

# Version - try importlib.metadata first (installed package), then pyproject.toml
def _read_version() -> str:
    """Read version from installed package metadata or pyproject.toml."""
    try:
        from importlib.metadata import version as _pkg_version

        return _pkg_version("bbcom-mcp")
    except Exception:
        pass
    try:
        toml_path = Path(__file__).parent / "pyproject.toml"
        if toml_path.exists():
            for line in toml_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("version"):
                    # version = "1.0.0"
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return "0.0.0-unknown"


__version__ = _read_version()

mcp = FastMCP("bbcom")


def _find_bbcom_exe() -> str | None:
    """Find BBCom executable using multiple search strategies.

    Search order (first match wins):
    1. BBCOM_EXE_PATH environment variable (developer override)
    2. PATH environment variable
    3. Windows registry Uninstall keys (NSIS/MSI installers)
    4. Common install locations (Program Files, LOCALAPPDATA, etc.)
    5. Same directory as runtime_status.json (dev build scenario)
    """
    # 1. BBCOM_EXE_PATH env var (highest priority, for custom locations)
    custom_path = os.environ.get("BBCOM_EXE_PATH", "")
    if custom_path and Path(custom_path).exists():
        return custom_path

    # 2. Search in PATH
    for path_dir in os.environ.get("PATH", "").split(os.pathsep):
        if not path_dir:
            continue
        exe_path = Path(path_dir) / BBCOM_EXE
        if exe_path.exists():
            return str(exe_path)

    # 3. Windows registry Uninstall keys
    if sys.platform == "win32":
        try:
            import winreg

            for hive_key in [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]:
                for access in [winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY]:
                    try:
                        key = winreg.OpenKey(
                            hive_key,
                            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                            access=access,
                        )
                        idx = 0
                        while True:
                            try:
                                subkey_name = winreg.EnumKey(key, idx)
                                idx += 1
                                subkey = winreg.OpenKey(key, subkey_name)
                                try:
                                    display_name, _ = winreg.QueryValueEx(
                                        subkey, "DisplayName"
                                    )
                                    if display_name and "BBCom" in display_name:
                                        install_loc, _ = winreg.QueryValueEx(
                                            subkey, "InstallLocation"
                                        )
                                        if install_loc:
                                            exe = Path(install_loc) / BBCOM_EXE
                                            if exe.exists():
                                                winreg.CloseKey(subkey)
                                                winreg.CloseKey(key)
                                                return str(exe)
                                except FileNotFoundError:
                                    pass
                                winreg.CloseKey(subkey)
                            except OSError:
                                break
                        winreg.CloseKey(key)
                    except OSError:
                        continue
        except ImportError:
            pass

    # 4. Common install locations
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    program_files = os.environ.get("ProgramFiles", "C:\\Program Files")
    program_files_x86 = os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")

    common_paths = [
        Path("D:/BBCom") / BBCOM_EXE,  # Default NSIS install path
        Path(program_files) / "BBCom" / BBCOM_EXE,
        Path(program_files_x86) / "BBCom" / BBCOM_EXE,
    ]
    if local_app_data:
        common_paths.extend(
            [
                Path(local_app_data) / "Programs" / "BBCom" / BBCOM_EXE,
                Path(local_app_data) / "Microsoft" / "WindowsApps" / BBCOM_EXE,
            ]
        )
    for p in common_paths:
        if p.exists():
            return str(p)

    # 5. Dev build: same directory as runtime_status.json
    if local_app_data:
        status_dir = Path(local_app_data) / "bbcom"
        exe = status_dir / BBCOM_EXE
        if exe.exists():
            return str(exe)

    return None


def _run_cli_command(*args: str) -> dict:
    """Run a BBCom CLI command and return parsed JSON result."""
    bbcom = _find_bbcom_exe()
    if not bbcom:
        return {
            "type": "error",
            "message": (
                "BBCom executable not found. Searched: BBCOM_EXE_PATH env, PATH, "
                "Windows registry, common install paths, LOCALAPPDATA/bbcom. "
                "Fix: set BBCOM_EXE_PATH env var in MCP config to point to bbcom.exe."
            ),
        }

    cmd = [bbcom, "--test"] + list(args)
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return {"type": "error", "message": f"Command failed: {result.stderr.strip()}"}

        # Parse JSON from stdout
        output = result.stdout.strip()
        if not output:
            # Try reading from cli_output.json as fallback
            local_app_data = os.environ.get("LOCALAPPDATA", "")
            if local_app_data:
                output_file = Path(local_app_data) / "bbcom" / "cli_output.json"
                if output_file.exists():
                    output = output_file.read_text().strip()

        if output:
            return json.loads(output)
        return {"type": "error", "message": "No output from command"}

    except subprocess.TimeoutExpired:
        return {"type": "error", "message": "Command timed out"}
    except json.JSONDecodeError as e:
        return {"type": "error", "message": f"Failed to parse output: {e}"}
    except Exception as e:
        return {"type": "error", "message": f"Command error: {e}"}


def _read_runtime_status() -> dict:
    """Read BBCom runtime status file directly."""
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if not local_app_data:
        return {
            "mirrorEnabled": False,
            "address": None,
            "port": None,
            "serialConnected": False,
            "terminalConnected": False,
            "clientCount": 0,
        }

    status_file = Path(local_app_data) / "bbcom" / "runtime_status.json"
    if not status_file.exists():
        return {
            "mirrorEnabled": False,
            "address": None,
            "port": None,
            "serialConnected": False,
            "terminalConnected": False,
            "clientCount": 0,
        }

    try:
        return json.loads(status_file.read_text())
    except Exception:
        return {
            "mirrorEnabled": False,
            "address": None,
            "port": None,
            "serialConnected": False,
            "terminalConnected": False,
            "clientCount": 0,
        }


def _mirror_tcp_read(host: str, port: int, duration_ms: int = 5000) -> dict:
    """Connect to mirror TCP server and read data."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect((host, port))
        sock.settimeout(0.5)

        lines = []
        total_bytes = 0
        start = time.time()

        while (time.time() - start) * 1000 < duration_ms:
            try:
                data = sock.recv(4096)
                if not data:
                    break
                total_bytes += len(data)
                text = data.decode("utf-8", errors="replace")
                for line in text.split("\n"):
                    line = line.strip()
                    if line:
                        lines.append(line)
            except socket.timeout:
                continue
            except Exception:
                break

        sock.close()
        return {"type": "mirror_read", "lines": lines, "bytes": total_bytes}

    except Exception as e:
        return {"type": "error", "message": f"Mirror read failed: {e}"}


def _mirror_tcp_read_until(
    host: str, port: int, pattern: str, timeout_ms: int = 30000, context_lines: int = 2
) -> dict:
    """Connect to mirror TCP server and read until pattern is matched or timeout.

    Args:
        host: Mirror server host
        port: Mirror server port
        pattern: Regex pattern to search for (case-insensitive)
        timeout_ms: Maximum time to wait in milliseconds
        context_lines: Number of lines to include after the match for context
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect((host, port))
        sock.settimeout(0.5)

        all_lines = []
        matched_lines = []
        match_indices = []
        total_bytes = 0
        start = time.time()
        pattern_re = re.compile(pattern, re.IGNORECASE)

        while (time.time() - start) * 1000 < timeout_ms:
            try:
                data = sock.recv(4096)
                if not data:
                    break
                total_bytes += len(data)
                text = data.decode("utf-8", errors="replace")
                for line in text.split("\n"):
                    line = line.strip()
                    if line:
                        all_lines.append(line)
                        if pattern_re.search(line):
                            match_indices.append(len(all_lines) - 1)
            except socket.timeout:
                if match_indices:
                    # Pattern found and no new data, wait a bit for context
                    elapsed = (time.time() - start) * 1000
                    if elapsed > 500:  # Give 500ms for context lines after last match
                        break
                continue
            except Exception:
                break

        sock.close()

        # Build matched results with context
        for idx in match_indices:
            start_idx = max(0, idx - context_lines)
            end_idx = min(len(all_lines), idx + context_lines + 1)
            for i in range(start_idx, end_idx):
                entry = {"line": all_lines[i], "index": i}
                if i == idx:
                    entry["matched"] = True
                matched_lines.append(entry)

        return {
            "type": "read_until",
            "pattern": pattern,
            "matched": len(match_indices) > 0,
            "matchCount": len(match_indices),
            "matchedLines": matched_lines,
            "totalLinesRead": len(all_lines),
            "totalBytesRead": total_bytes,
            "timedOut": len(match_indices) == 0,
            "elapsedMs": int((time.time() - start) * 1000),
        }

    except Exception as e:
        return {"type": "error", "message": f"Mirror read_until failed: {e}"}


def _mirror_tcp_send(host: str, port: int, data: str) -> dict:
    """Connect to mirror TCP server and send data."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect((host, port))

        send_data = data + "\n"
        sock.sendall(send_data.encode("utf-8"))
        sock.close()
        return {"type": "mirror_send", "bytes": len(send_data)}

    except Exception as e:
        return {"type": "error", "message": f"Mirror send failed: {e}"}


def _mirror_tcp_send_and_read(
    host: str, port: int, data: str, read_duration_ms: int = 5000
) -> dict:
    """Connect to mirror, start reading, then send command and capture response."""
    reader_lines = []
    reader_bytes = 0
    reader_error = None
    reader_ready = threading.Event()

    def _reader():
        nonlocal reader_lines, reader_bytes, reader_error
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5.0)
            sock.connect((host, port))
            sock.settimeout(0.5)
            reader_ready.set()

            start = time.time()
            while (time.time() - start) * 1000 < read_duration_ms:
                try:
                    recv_data = sock.recv(4096)
                    if not recv_data:
                        break
                    reader_bytes += len(recv_data)
                    text = recv_data.decode("utf-8", errors="replace")
                    for line in text.split("\n"):
                        line = line.strip()
                        if line:
                            reader_lines.append(line)
                except socket.timeout:
                    continue
                except Exception:
                    break

            sock.close()
        except Exception as e:
            reader_error = str(e)
            reader_ready.set()

    reader_thread = threading.Thread(target=_reader, daemon=True)
    reader_thread.start()

    if not reader_ready.wait(timeout=5.0):
        return {"type": "error", "message": "Reader connection timed out"}

    if reader_error:
        return {"type": "error", "message": f"Reader connection failed: {reader_error}"}

    send_result = _mirror_tcp_send(host, port, data)
    if send_result.get("type") == "error":
        reader_thread.join(timeout=read_duration_ms / 1000 + 1)
        return send_result

    reader_thread.join(timeout=read_duration_ms / 1000 + 1)

    return {
        "type": "send_and_read",
        "sent": {"data": data, "bytes": send_result.get("bytes", 0)},
        "response": {"lines": reader_lines, "bytes": reader_bytes},
    }


def _mirror_tcp_send_and_read_until(
    host: str,
    port: int,
    data: str,
    pattern: str,
    timeout_ms: int = 30000,
    context_lines: int = 2,
) -> dict:
    """Send a command and read until pattern is matched in the response.

    1. Start a reader thread first
    2. Send the command via a separate connection
    3. Reader collects data until pattern matches or timeout
    4. Return only matched lines with context (minimal data transfer)
    """
    reader_lines = []
    reader_bytes = 0
    reader_error = None
    reader_ready = threading.Event()
    match_found = threading.Event()
    match_indices = []

    def _reader():
        nonlocal reader_lines, reader_bytes, reader_error, match_indices
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5.0)
            sock.connect((host, port))
            sock.settimeout(0.5)
            reader_ready.set()

            pattern_re = re.compile(pattern, re.IGNORECASE)
            start = time.time()

            while (time.time() - start) * 1000 < timeout_ms:
                if match_found.is_set():
                    # Wait a short time for context lines after match
                    time.sleep(0.3)
                    break
                try:
                    recv_data = sock.recv(4096)
                    if not recv_data:
                        break
                    reader_bytes += len(recv_data)
                    text = recv_data.decode("utf-8", errors="replace")
                    for line in text.split("\n"):
                        line = line.strip()
                        if line:
                            reader_lines.append(line)
                            if pattern_re.search(line):
                                match_indices.append(len(reader_lines) - 1)
                                match_found.set()
                except socket.timeout:
                    continue
                except Exception:
                    break

            sock.close()
        except Exception as e:
            reader_error = str(e)
            reader_ready.set()

    # Start reader
    reader_thread = threading.Thread(target=_reader, daemon=True)
    reader_thread.start()

    if not reader_ready.wait(timeout=5.0):
        return {"type": "error", "message": "Reader connection timed out"}

    if reader_error:
        return {"type": "error", "message": f"Reader connection failed: {reader_error}"}

    # Send command
    send_result = _mirror_tcp_send(host, port, data)
    if send_result.get("type") == "error":
        match_found.set()  # Unblock reader
        reader_thread.join(timeout=2)
        return send_result

    # Wait for match or timeout
    reader_thread.join(timeout=timeout_ms / 1000 + 1)

    # Build matched results with context
    matched_lines = []
    for idx in match_indices:
        start_idx = max(0, idx - context_lines)
        end_idx = min(len(reader_lines), idx + context_lines + 1)
        for i in range(start_idx, end_idx):
            entry = {"line": reader_lines[i], "index": i}
            if i == idx:
                entry["matched"] = True
            matched_lines.append(entry)

    return {
        "type": "send_and_read_until",
        "sent": {"data": data, "bytes": send_result.get("bytes", 0)},
        "pattern": pattern,
        "matched": len(match_indices) > 0,
        "matchCount": len(match_indices),
        "matchedLines": matched_lines,
        "totalLinesRead": len(reader_lines),
        "totalBytesRead": reader_bytes,
        "timedOut": len(match_indices) == 0,
    }


def _mirror_tcp_monitor(
    host: str,
    port: int,
    patterns: list[str],
    duration_ms: int = 30000,
    context_lines: int = 1,
) -> dict:
    """Monitor serial data for multiple pattern matches.

    Reads continuously for duration_ms and returns only lines that match
    any of the specified patterns, plus surrounding context. This is efficient
    because it filters out non-matching data, reducing the amount of data
    the LLM needs to process.
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect((host, port))
        sock.settimeout(0.5)

        all_lines = []
        total_bytes = 0
        start = time.time()

        # Compile all patterns
        pattern_res = [re.compile(p, re.IGNORECASE) for p in patterns]

        # Track matches: {pattern_index: [line_indices]}
        matches = {i: [] for i in range(len(patterns))}

        while (time.time() - start) * 1000 < duration_ms:
            try:
                data = sock.recv(4096)
                if not data:
                    break
                total_bytes += len(data)
                text = data.decode("utf-8", errors="replace")
                for line in text.split("\n"):
                    line = line.strip()
                    if line:
                        line_idx = len(all_lines)
                        all_lines.append(line)
                        for pi, pat_re in enumerate(pattern_res):
                            if pat_re.search(line):
                                matches[pi].append(line_idx)
            except socket.timeout:
                continue
            except Exception:
                break

        sock.close()

        # Build results: unique matched lines with context
        seen_indices = set()
        result_matches = []

        for pi, pat in enumerate(patterns):
            line_indices = matches[pi]
            for idx in line_indices:
                start_idx = max(0, idx - context_lines)
                end_idx = min(len(all_lines), idx + context_lines + 1)
                context = []
                for i in range(start_idx, end_idx):
                    entry = {"line": all_lines[i], "index": i}
                    if i == idx:
                        entry["matched"] = True
                        entry["pattern"] = pat
                    context.append(entry)
                    seen_indices.add(i)
                result_matches.append(
                    {
                        "pattern": pat,
                        "line": all_lines[idx],
                        "lineIndex": idx,
                        "context": context,
                    }
                )

        total_matches = sum(len(v) for v in matches.values())

        return {
            "type": "monitor",
            "patterns": patterns,
            "totalMatches": total_matches,
            "matches": result_matches,
            "totalLinesRead": len(all_lines),
            "totalBytesRead": total_bytes,
            "elapsedMs": int((time.time() - start) * 1000),
            "summary": f"Monitored {len(all_lines)} lines, found {total_matches} match(es) across {len(patterns)} pattern(s)",
        }

    except Exception as e:
        return {"type": "error", "message": f"Mirror monitor failed: {e}"}


# ── Tool Definitions ──────────────────────────────────────────────────────────


@mcp.tool()
def bbcom_version() -> str:
    """Get the version of the BBCom MCP server. Returns the server name and
    version string. Use this to verify which version of the MCP server is
    running and for diagnostic purposes."""
    return json.dumps({"name": "bbcom-mcp", "version": __version__}, indent=2)


@mcp.tool()
def bbcom_status() -> str:
    """Get BBCom serial communication tool status. Returns mirror status,
    serial connection info, and terminal connection info. Use this first
    to discover if BBCom has mirror mode enabled and how to connect."""
    status = _read_runtime_status()
    return json.dumps(status, indent=2)


@mcp.tool()
def bbcom_mirror_status() -> str:
    """Get detailed mirror status from BBCom. Returns whether mirror is enabled,
    the TCP address and port that serial data is being mirrored to, and how
    many clients are connected. If mirror is enabled, use the address and port
    with bbcom_mirror_read, bbcom_mirror_send, or bbcom_mirror_send_and_read."""
    status = _read_runtime_status()
    mirror_info = {
        "mirrorEnabled": status.get("mirrorEnabled", False),
        "address": status.get("address"),
        "port": status.get("port"),
        "serialConnected": status.get("serialConnected", False),
        "terminalConnected": status.get("terminalConnected", False),
        "clientCount": status.get("clientCount", 0),
    }
    return json.dumps(mirror_info, indent=2)


@mcp.tool()
def bbcom_serial_status() -> str:
    """Get serial port status from BBCom. Returns whether a serial port is
    connected, the port name, and baud rate. Reads from runtime status file."""
    status = _read_runtime_status()
    serial_info = {
        "serialConnected": status.get("serialConnected", False),
        "serialPort": status.get("serialPort"),
        "baudRate": status.get("baudRate"),
    }
    return json.dumps(serial_info, indent=2)


@mcp.tool()
def bbcom_mirror_read(port: int, host: str = "127.0.0.1", duration_ms: int = 5000) -> str:
    """Read real-time serial data from BBCom's mirror TCP server. Connects to
    the mirror port and collects data for the specified duration. Returns
    an array of formatted log lines with timestamps, direction markers, and
    content. Use this for passive monitoring of serial data.

    IMPORTANT: If you need to send a command AND capture the response, use
    bbcom_mirror_send_and_read instead. Using separate send and read calls
    may miss the response due to timing delays between tool invocations.

    TIP: If you are waiting for a specific pattern (e.g. HARDFAULT, FATAL ERROR,
    boot complete), use bbcom_mirror_read_until or bbcom_mirror_monitor instead
    to avoid processing excessive non-matching data.

    Args:
        port: Mirror server port number (e.g. 12345)
        host: Mirror server host address (default: 127.0.0.1)
        duration_ms: How long to read data in milliseconds (default: 5000)
    """
    result = _mirror_tcp_read(host, port, duration_ms)
    return json.dumps(result, indent=2)


@mcp.tool()
def bbcom_mirror_send(port: int, data: str, host: str = "127.0.0.1") -> str:
    """Send data through BBCom's mirror TCP server. The data will be forwarded
    to the serial port as a TX transmission. Use this to send commands to
    the serial device when you do NOT need to capture the response.

    IMPORTANT: If you need to send a command AND capture the response, use
    bbcom_mirror_send_and_read or bbcom_mirror_send_and_read_until instead.

    Args:
        port: Mirror server port number (e.g. 12345)
        data: Data to send to the serial device
        host: Mirror server host address (default: 127.0.0.1)
    """
    result = _mirror_tcp_send(host, port, data)
    return json.dumps(result, indent=2)


@mcp.tool()
def bbcom_mirror_send_and_read(
    port: int,
    data: str,
    host: str = "127.0.0.1",
    read_duration_ms: int = 5000,
) -> str:
    """Send a command to the serial device AND capture the response atomically.
    This is the RECOMMENDED way to send commands when you need to see the
    device's response, because it starts reading BEFORE sending to ensure no
    response data is missed.

    How it works:
    1. Opens a reader connection to the mirror TCP server first
    2. Sends the command via a separate connection
    3. Collects response data on the reader connection for read_duration_ms
    4. Returns both the send confirmation and captured response lines

    TIP: If you are waiting for a specific response pattern (e.g. a prompt,
    a specific message), use bbcom_mirror_send_and_read_until instead, which
    stops reading as soon as the pattern is found and returns only matches.

    Args:
        port: Mirror server port number (e.g. 12345)
        data: Command to send to the serial device
        host: Mirror server host address (default: 127.0.0.1)
        read_duration_ms: How long to read response data in milliseconds (default: 5000)
    """
    result = _mirror_tcp_send_and_read(host, port, data, read_duration_ms)
    return json.dumps(result, indent=2)


@mcp.tool()
def bbcom_mirror_read_until(
    port: int,
    pattern: str,
    host: str = "127.0.0.1",
    timeout_ms: int = 30000,
    context_lines: int = 2,
) -> str:
    """Read serial data until a specific pattern is matched, or timeout is reached.
    This is ideal for waiting for critical events like HARDFAULT, FATAL ERROR,
    boot completion, or any specific marker in the serial output.

    The pattern is a regex matched case-insensitively. Reading stops as soon as
    the pattern is found (plus a few context lines), or when timeout_ms elapses.

    Returns only the matched lines and their surrounding context, minimizing
    unnecessary data transfer to the LLM.

    Examples:
    - pattern="HARDFAULT" - Wait for a hard fault event
    - pattern="FATAL ERROR" - Wait for a fatal error
    - pattern="Boot complete" - Wait for system boot to finish
    - pattern="Assertion failed" - Wait for assertion failures
    - pattern="ESP32.*ready" - Wait for ESP32 ready message

    Args:
        port: Mirror server port number (e.g. 12345)
        pattern: Regex pattern to search for (case-insensitive)
        host: Mirror server host address (default: 127.0.0.1)
        timeout_ms: Maximum time to wait in milliseconds (default: 30000)
        context_lines: Number of lines before/after match for context (default: 2)
    """
    result = _mirror_tcp_read_until(host, port, pattern, timeout_ms, context_lines)
    return json.dumps(result, indent=2)


@mcp.tool()
def bbcom_mirror_send_and_read_until(
    port: int,
    data: str,
    pattern: str,
    host: str = "127.0.0.1",
    timeout_ms: int = 30000,
    context_lines: int = 2,
) -> str:
    """Send a command and read until a specific pattern appears in the response.
    This combines sending and pattern-based reading into a single atomic operation.

    How it works:
    1. Opens a reader connection to the mirror TCP server first
    2. Sends the command via a separate connection
    3. Reader collects data until the pattern is matched or timeout
    4. Returns only matched lines with context (minimal data transfer)

    This is ideal for sending a command and waiting for a specific response
    pattern, such as:
    - Send "ping" and wait for "PONG"
    - Send "reset" and wait for "Boot complete"
    - Send "test" and wait for "PASS" or "FAIL"

    Args:
        port: Mirror server port number (e.g. 12345)
        data: Command to send to the serial device
        pattern: Regex pattern to search for in response (case-insensitive)
        host: Mirror server host address (default: 127.0.0.1)
        timeout_ms: Maximum time to wait for pattern in milliseconds (default: 30000)
        context_lines: Number of lines before/after match for context (default: 2)
    """
    result = _mirror_tcp_send_and_read_until(
        host, port, data, pattern, timeout_ms, context_lines
    )
    return json.dumps(result, indent=2)


@mcp.tool()
def bbcom_mirror_monitor(
    port: int,
    patterns: str,
    host: str = "127.0.0.1",
    duration_ms: int = 30000,
    context_lines: int = 1,
) -> str:
    """Monitor serial data for multiple pattern matches over a period of time.
    Only returns lines that match any of the specified patterns plus context,
    filtering out all non-matching data. This is very efficient for LLMs
    because it avoids processing large volumes of irrelevant serial data.

    Use this for long-running monitoring tasks like:
    - Watching for error patterns: "HARDFAULT|FATAL ERROR|Assertion failed"
    - Monitoring for specific events: "connected|disconnected|timeout"
    - Tracking multiple keywords: "ERROR|WARN|CRITICAL|ALERT"

    The patterns parameter accepts pipe-separated regex patterns (OR logic).
    All patterns are matched case-insensitively.

    Examples:
    - patterns="HARDFAULT|FATAL ERROR|Watchdog" - Monitor for critical errors
    - patterns="ERROR|WARN" - Monitor for error and warning messages
    - patterns="connected|disconnected" - Monitor connection state changes
    - patterns="boot|ready|start" - Monitor boot/startup sequence

    Args:
        port: Mirror server port number (e.g. 12345)
        patterns: Pipe-separated regex patterns to monitor (OR logic, case-insensitive).
                  Example: "HARDFAULT|FATAL ERROR|Watchdog"
        host: Mirror server host address (default: 127.0.0.1)
        duration_ms: How long to monitor in milliseconds (default: 30000)
        context_lines: Number of lines before/after each match for context (default: 1)
    """
    pattern_list = [p.strip() for p in patterns.split("|") if p.strip()]
    if not pattern_list:
        return json.dumps(
            {"type": "error", "message": "No valid patterns provided"}, indent=2
        )

    result = _mirror_tcp_monitor(host, port, pattern_list, duration_ms, context_lines)
    return json.dumps(result, indent=2)


@mcp.tool()
def bbcom_list_ports() -> str:
    """List available serial ports and debug probes. Returns port names and
    types that can be used to connect."""
    result = _run_cli_command("list-ports")
    return json.dumps(result, indent=2)


@mcp.tool()
def bbcom_get_config() -> str:
    """Get BBCom configuration. Returns current settings including baud rate,
    display mode, encoding, and other serial/terminal options."""
    result = _run_cli_command("get-config")
    return json.dumps(result, indent=2)


@mcp.tool()
def bbcom_set_baud_rate(baud_rate: int) -> str:
    """Set serial port baud rate. The change takes effect on next connection.
    Common values: 9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600.

    Args:
        baud_rate: Baud rate value (e.g. 115200)
    """
    result = _run_cli_command("set-baud-rate", str(baud_rate))
    return json.dumps(result, indent=2)


@mcp.tool()
def bbcom_set_display_mode(mode: str) -> str:
    """Set display mode for serial data. Affects how data is shown in the log
    and in mirror output.

    Args:
        mode: Display mode: 'ascii' or 'hex'
    """
    result = _run_cli_command("set-display", mode)
    return json.dumps(result, indent=2)


def _mirror_tcp_control(host: str, port: int, command: str) -> dict:
    """Send a control command through Mirror TCP and optionally read response.

    Control commands use the \\x01 prefix to distinguish them from normal data.
    After sending, waits briefly and reads any response data.
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect((host, port))

        # Control command format: \x01<COMMAND>:<params>\n
        control_data = f"\x01{command}\n"
        sock.sendall(control_data.encode("utf-8"))

        # Wait briefly for command to be processed
        time.sleep(0.3)

        # Try to read response (best effort)
        sock.settimeout(0.5)
        response_lines = []
        try:
            while True:
                data = sock.recv(4096)
                if not data:
                    break
                text = data.decode("utf-8", errors="replace")
                for line in text.split("\n"):
                    line = line.strip()
                    if line:
                        response_lines.append(line)
        except socket.timeout:
            pass

        sock.close()

        return {
            "type": "mirror_control",
            "command": command,
            "success": True,
            "response": response_lines,
            "message": f"Control command sent: {command}",
        }

    except Exception as e:
        return {"type": "error", "message": f"Mirror control failed: {e}"}


def _get_mirror_connection() -> tuple[str, int] | None:
    """Get Mirror TCP host and port from runtime status.

    Returns (host, port) tuple or None if mirror is not enabled.
    """
    status = _read_runtime_status()
    if not status.get("mirrorEnabled", False):
        return None
    host = status.get("address", "127.0.0.1")
    if host == "0.0.0.0":
        host = "127.0.0.1"
    port = status.get("port")
    if port is None:
        return None
    return (host, int(port))


@mcp.tool()
def bbcom_connect(port_name: str, baud_rate: int = 115200) -> str:
    """Connect to a serial port through BBCom. This sends a control command
    via the Mirror TCP connection to tell the running BBCom instance to
    open the specified serial port.

    IMPORTANT: BBCom must be running with Mirror mode enabled for this
    to work. Use bbcom_status first to check.

    Args:
        port_name: Serial port name (e.g. 'COM3', '/dev/ttyUSB0')
        baud_rate: Baud rate (default: 115200)
    """
    conn = _get_mirror_connection()
    if conn is None:
        return json.dumps({
            "type": "error",
            "message": "Mirror mode not enabled. Enable mirror mode in BBCom first.",
        }, indent=2)

    host, port = conn
    command = f"CONNECT:{port_name},{baud_rate}"
    result = _mirror_tcp_control(host, port, command)

    # Wait and verify connection status
    time.sleep(0.5)
    status = _read_runtime_status()
    connected = status.get("serialConnected", False)
    connected_port = status.get("serialPort")

    if connected and connected_port == port_name:
        result["verified"] = True
        result["message"] = f"Successfully connected to {port_name} at {baud_rate} baud"
    else:
        result["verified"] = False
        result["message"] = (
            f"Connect command sent, but verification shows "
            f"serialConnected={connected}, serialPort={connected_port}"
        )

    return json.dumps(result, indent=2)


@mcp.tool()
def bbcom_disconnect() -> str:
    """Disconnect from the current serial port through BBCom. This sends a
    control command via the Mirror TCP connection to tell the running BBCom
    instance to close the serial port.

    IMPORTANT: BBCom must be running with Mirror mode enabled for this
    to work. Use bbcom_status first to check.
    """
    conn = _get_mirror_connection()
    if conn is None:
        return json.dumps({
            "type": "error",
            "message": "Mirror mode not enabled. Enable mirror mode in BBCom first.",
        }, indent=2)

    host, port = conn
    command = "DISCONNECT"
    result = _mirror_tcp_control(host, port, command)

    # Wait and verify disconnection
    time.sleep(0.5)
    status = _read_runtime_status()
    connected = status.get("serialConnected", False)

    if not connected:
        result["verified"] = True
        result["message"] = "Successfully disconnected from serial port"
    else:
        result["verified"] = False
        result["message"] = f"Disconnect command sent, but serialConnected={connected}"

    return json.dumps(result, indent=2)


@mcp.tool()
def bbcom_set_signals(rts: bool | None = None, dtr: bool | None = None) -> str:
    """Set serial port control signals (RTS/DTR). This allows toggling the
    RTS (Request To Send) and DTR (Data Terminal Ready) control lines at
    runtime. Essential for entering ESP32 download mode, which requires
    specific RTS/DTR timing sequences.

    IMPORTANT: BBCom must be connected to a serial port AND have Mirror mode
    enabled. Use bbcom_status first to check.

    Common ESP32 download mode sequences:
    1. Set RTS=1, DTR=0 (EN low, IO0 low -> reset into download)
    2. Set RTS=0, DTR=1 (EN high, IO0 still low -> run in download mode)
    3. Set RTS=0, DTR=0 (normal operation)

    Args:
        rts: Set RTS signal level (True=high, False=low, None=no change)
        dtr: Set DTR signal level (True=high, False=low, None=no change)
    """
    if rts is None and dtr is None:
        return json.dumps({
            "type": "error",
            "message": "At least one of rts or dtr must be specified",
        }, indent=2)

    conn = _get_mirror_connection()
    if conn is None:
        return json.dumps({
            "type": "error",
            "message": "Mirror mode not enabled. Enable mirror mode in BBCom first.",
        }, indent=2)

    host, port = conn

    # Build SIGNALS command
    parts = []
    if rts is not None:
        parts.append(f"RTS={1 if rts else 0}")
    if dtr is not None:
        parts.append(f"DTR={1 if dtr else 0}")
    command = f"SIGNALS:{','.join(parts)}"

    result = _mirror_tcp_control(host, port, command)
    return json.dumps(result, indent=2)


@mcp.tool()
def bbcom_set_serial_config(
    baud_rate: int | None = None,
    data_bits: str | None = None,
    parity: str | None = None,
    stop_bits: str | None = None,
    flow_control: str | None = None,
) -> str:
    """Set serial port configuration parameters. Changes take effect on next
    connection. Use bbcom_connect to reconnect with new settings.

    IMPORTANT: BBCom must be running with Mirror mode enabled for this
    to work. Use bbcom_status first to check.

    Args:
        baud_rate: Baud rate (e.g. 9600, 115200, 921600)
        data_bits: Data bits: '5', '6', '7', or '8'
        parity: Parity: 'none', 'odd', or 'even'
        stop_bits: Stop bits: '1' or '2'
        flow_control: Flow control: 'none', 'software', or 'hardware'
    """
    if all(v is None for v in [baud_rate, data_bits, parity, stop_bits, flow_control]):
        return json.dumps({
            "type": "error",
            "message": "At least one configuration parameter must be specified",
        }, indent=2)

    conn = _get_mirror_connection()
    if conn is None:
        return json.dumps({
            "type": "error",
            "message": "Mirror mode not enabled. Enable mirror mode in BBCom first.",
        }, indent=2)

    host, port = conn

    # Build CONFIG command
    parts = []
    if baud_rate is not None:
        parts.append(f"baud={baud_rate}")
    if data_bits is not None:
        if data_bits not in ("5", "6", "7", "8"):
            return json.dumps({
                "type": "error",
                "message": f"Invalid data_bits '{data_bits}'. Must be 5, 6, 7, or 8",
            }, indent=2)
        parts.append(f"data={data_bits}")
    if parity is not None:
        if parity not in ("none", "odd", "even"):
            return json.dumps({
                "type": "error",
                "message": f"Invalid parity '{parity}'. Must be none, odd, or even",
            }, indent=2)
        parts.append(f"parity={parity}")
    if stop_bits is not None:
        if stop_bits not in ("1", "2"):
            return json.dumps({
                "type": "error",
                "message": f"Invalid stop_bits '{stop_bits}'. Must be 1 or 2",
            }, indent=2)
        parts.append(f"stop={stop_bits}")
    if flow_control is not None:
        if flow_control not in ("none", "software", "hardware"):
            return json.dumps({
                "type": "error",
                "message": f"Invalid flow_control '{flow_control}'. Must be none, software, or hardware",
            }, indent=2)
        parts.append(f"flow={flow_control}")

    command = f"CONFIG:{','.join(parts)}"
    result = _mirror_tcp_control(host, port, command)
    return json.dumps(result, indent=2)


def main():
    """Entry point for the MCP server (used by pyproject.toml script)."""
    parser = argparse.ArgumentParser(
        prog="bbcom-mcp",
        description="BBCom MCP Server - Model Context Protocol server for BBCom serial communication tool",
        add_help=True,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"bbcom-mcp {__version__}",
    )
    # Parse known args to avoid conflicts with MCP stdio protocol
    parser.parse_known_args()

    mcp.run()


if __name__ == "__main__":
    main()
