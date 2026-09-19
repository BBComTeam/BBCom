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
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            return {"type": "error", "message": f"Command failed: {(result.stderr or '').strip()}"}

        # Parse JSON from stdout
        output = (result.stdout or '').strip()
        if not output:
            # Try reading from cli_output.json as fallback. Guard against stale
            # results from a PREVIOUS command: only accept files written within
            # the last 10 seconds.
            local_app_data = os.environ.get("LOCALAPPDATA", "")
            if local_app_data:
                output_file = Path(local_app_data) / "bbcom" / "cli_output.json"
                if output_file.exists():
                    try:
                        if time.time() - output_file.stat().st_mtime < 10:
                            output = output_file.read_text().strip()
                    except OSError:
                        pass

        if output:
            return json.loads(output)
        return {"type": "error", "message": "No output from command"}

    except subprocess.TimeoutExpired:
        return {"type": "error", "message": "Command timed out"}
    except json.JSONDecodeError as e:
        return {"type": "error", "message": f"Failed to parse output: {e}"}
    except Exception as e:
        return {"type": "error", "message": f"Command error: {e}"}


def _empty_runtime_status() -> dict:
    """Default status used when BBCom is not running / status unavailable."""
    return {
        "mirrorEnabled": False,
        "address": None,
        "port": None,
        "serialConnected": False,
        "terminalConnected": False,
        "clientCount": 0,
        "stale": False,
    }


def _process_alive(pid: int) -> bool:
    """Check whether a process id is alive (Windows, no external deps)."""
    if pid <= 0:
        return False
    try:
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return exit_code.value == STILL_ACTIVE
            return True
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        # If liveness cannot be determined, assume alive (avoid false negatives).
        return True


def _read_runtime_status(max_age_seconds: float = 0.0) -> dict:
    """Read BBCom runtime status file directly.

    Detects stale status files (BBCom crashed / exited uncleanly):
    - the file carries the writer's ``pid`` → checked for process liveness;
    - ``max_age_seconds`` > 0 additionally rejects files whose mtime is older
      than the given age (heartbeat mode).
    Stale statuses get ``mirrorEnabled=False`` and ``stale=True`` so callers
    report "BBCom not running" instead of trying to connect to a dead mirror.
    """
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if not local_app_data:
        return _empty_runtime_status()

    status_file = Path(local_app_data) / "bbcom" / "runtime_status.json"
    if not status_file.exists():
        return _empty_runtime_status()

    try:
        status = json.loads(status_file.read_text())
    except Exception:
        return _empty_runtime_status()

    if not isinstance(status, dict):
        return _empty_runtime_status()

    # Staleness detection
    stale = False
    stale_reason = None
    if max_age_seconds > 0:
        try:
            age = time.time() - status_file.stat().st_mtime
            if age > max_age_seconds:
                stale = True
                stale_reason = f"status file age {age:.0f}s > {max_age_seconds:.0f}s"
        except OSError:
            pass
    pid = status.get("pid")
    if not stale and isinstance(pid, int) and pid > 0:
        if not _process_alive(pid):
            stale = True
            stale_reason = f"writer process {pid} is not running"

    if stale:
        result = _empty_runtime_status()
        result["stale"] = True
        result["staleReason"] = stale_reason
        return result
    return status



def _mirror_tcp_read(host: str, port: int, duration_ms: int = 5000, raw: bool = False) -> dict:
    """Connect to mirror TCP server and read data.

    Args:
        host: Mirror server host
        port: Mirror server port
        duration_ms: Read duration in milliseconds
        raw: If True, switch to raw mode first (no tags/timestamps/newlines, 1:1 serial data)
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect((host, port))

        # Switch to raw mode if requested
        if raw:
            sock.sendall(b"\x01RAW\n")
            time.sleep(0.1)  # Wait for mode switch

        sock.settimeout(0.5)

        if raw:
            # Raw mode: read binary data, no line splitting
            chunks = []
            total_bytes = 0
            start = time.time()

            while (time.time() - start) * 1000 < duration_ms:
                try:
                    data = sock.recv(4096)
                    if not data:
                        break
                    total_bytes += len(data)
                    chunks.append(data)
                except socket.timeout:
                    continue
                except Exception:
                    break

            # Switch back to formatted mode before closing
            try:
                sock.sendall(b"\x01FORMATTED\n")
            except Exception:
                pass
            sock.close()

            raw_bytes = b"".join(chunks)
            return {
                "type": "mirror_read_raw",
                "data": raw_bytes.hex(),
                "bytes": total_bytes,
            }
        else:
            # Formatted mode: read text lines
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
    host: str, port: int, pattern: str, timeout_ms: int = 30000, context_lines: int = 2,
    raw: bool = False
) -> dict:
    """Connect to mirror TCP server and read until pattern is matched or timeout.

    Args:
        host: Mirror server host
        port: Mirror server port
        pattern: Regex pattern to search for (case-insensitive)
        timeout_ms: Maximum time to wait in milliseconds
        context_lines: Number of lines to include after the match for context
        raw: If True, switch to raw mode first
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect((host, port))

        # Switch to raw mode if requested
        if raw:
            sock.sendall(b"\x01RAW\n")
            time.sleep(0.1)

        sock.settimeout(0.5)

        if raw:
            # Raw mode: read binary data and search pattern in hex representation
            all_chunks = []
            total_bytes = 0
            match_offset = -1
            start = time.time()
            pattern_re = re.compile(pattern, re.IGNORECASE)

            while (time.time() - start) * 1000 < timeout_ms:
                try:
                    data = sock.recv(4096)
                    if not data:
                        break
                    total_bytes += len(data)
                    all_chunks.append(data)
                    # Check pattern in ASCII representation of accumulated data
                    combined = b"".join(all_chunks)
                    try:
                        text = combined.decode("utf-8", errors="replace")
                    except Exception:
                        text = combined.hex()
                    if pattern_re.search(text):
                        match_offset = total_bytes
                        # Wait a bit for context after match
                        time.sleep(0.3)
                        break
                except socket.timeout:
                    if match_offset >= 0:
                        break
                    continue
                except Exception:
                    break

            # Switch back to formatted mode
            try:
                sock.sendall(b"\x01FORMATTED\n")
            except Exception:
                pass
            sock.close()

            combined = b"".join(all_chunks)
            try:
                matched_text = combined.decode("utf-8", errors="replace")
            except Exception:
                matched_text = combined.hex()

            return {
                "type": "read_until_raw",
                "pattern": pattern,
                "matched": match_offset >= 0,
                "data": combined.hex(),
                "dataAsciiPreview": matched_text[:500] if matched_text else "",
                "totalBytesRead": total_bytes,
                "timedOut": match_offset < 0,
                "elapsedMs": int((time.time() - start) * 1000),
            }
        else:
            # Formatted mode (existing logic)
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


def _mirror_tcp_send(host: str, port: int, data: str, raw: bool = False, hex_data: bool = False) -> dict:
    """Connect to mirror TCP server and send data.

    Args:
        host: Mirror server host
        port: Mirror server port
        data: Data to send (text or hex string)
        raw: If True, switch to raw mode first (send exact bytes, no modifications)
        hex_data: If True, treat data as hex string (e.g. "48656c6c6f") and decode to bytes
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect((host, port))

        if raw:
            # Switch to raw mode
            sock.sendall(b"\x01RAW\n")
            time.sleep(0.1)

            # Prepare raw bytes to send
            if hex_data:
                try:
                    send_bytes = bytes.fromhex(data.replace(" ", ""))
                except ValueError as e:
                    sock.close()
                    return {"type": "error", "message": f"Invalid hex data: {e}"}
            else:
                send_bytes = data.encode("utf-8")

            # In raw mode, send exact bytes without any modification (no \\n suffix)
            sock.sendall(send_bytes)

            # Switch back to formatted mode
            time.sleep(0.1)
            try:
                sock.sendall(b"\x01FORMATTED\n")
            except Exception:
                pass
            sock.close()

            return {
                "type": "mirror_send_raw",
                "bytes": len(send_bytes),
                "hexData": hex_data,
                "hexSent": send_bytes.hex(),
            }
        else:
            # Formatted mode: send text with newline suffix
            send_data = data + "\n"
            sock.sendall(send_data.encode("utf-8"))
            sock.close()
            return {"type": "mirror_send", "bytes": len(send_data)}

    except Exception as e:
        return {"type": "error", "message": f"Mirror send failed: {e}"}


def _mirror_tcp_send_and_read(
    host: str, port: int, data: str, read_duration_ms: int = 5000,
    raw: bool = False, hex_data: bool = False
) -> dict:
    """Connect to mirror, start reading, then send command and capture response."""
    if raw:
        # Raw mode: single connection, send RAW command, then send data, then read
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5.0)
            sock.connect((host, port))

            # Switch to raw mode
            sock.sendall(b"\x01RAW\n")
            time.sleep(0.1)

            # Prepare send bytes
            if hex_data:
                try:
                    send_bytes = bytes.fromhex(data.replace(" ", ""))
                except ValueError as e:
                    sock.close()
                    return {"type": "error", "message": f"Invalid hex data: {e}"}
            else:
                send_bytes = data.encode("utf-8")

            # Send raw data
            sock.sendall(send_bytes)

            # Read raw response
            chunks = []
            total_bytes = 0
            start = time.time()

            while (time.time() - start) * 1000 < read_duration_ms:
                try:
                    recv_data = sock.recv(4096)
                    if not recv_data:
                        break
                    total_bytes += len(recv_data)
                    chunks.append(recv_data)
                except socket.timeout:
                    continue
                except Exception:
                    break

            # Switch back to formatted mode
            try:
                sock.sendall(b"\x01FORMATTED\n")
            except Exception:
                pass
            sock.close()

            raw_response = b"".join(chunks)
            return {
                "type": "send_and_read_raw",
                "sent": {"data": data, "bytes": len(send_bytes), "hexSent": send_bytes.hex()},
                "response": {"data": raw_response.hex(), "bytes": total_bytes},
            }
        except Exception as e:
            return {"type": "error", "message": f"Raw send_and_read failed: {e}"}
    else:
        # Formatted mode: separate reader and sender threads
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
    raw: bool = False,
    hex_data: bool = False,
) -> dict:
    """Send a command and read until pattern is matched in the response.

    1. Start a reader thread first
    2. Send the command via a separate connection
    3. Reader collects data until pattern matches or timeout
    4. Return only matched lines with context (minimal data transfer)
    """
    if raw:
        # Raw mode: single connection approach
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5.0)
            sock.connect((host, port))

            # Switch to raw mode
            sock.sendall(b"\x01RAW\n")
            time.sleep(0.1)

            # Prepare send bytes
            if hex_data:
                try:
                    send_bytes = bytes.fromhex(data.replace(" ", ""))
                except ValueError as e:
                    sock.close()
                    return {"type": "error", "message": f"Invalid hex data: {e}"}
            else:
                send_bytes = data.encode("utf-8")

            # Send raw data
            sock.sendall(send_bytes)

            # Read until pattern matches or timeout
            all_chunks = []
            total_bytes = 0
            match_offset = -1
            pattern_re = re.compile(pattern, re.IGNORECASE)
            start = time.time()

            while (time.time() - start) * 1000 < timeout_ms:
                try:
                    recv_data = sock.recv(4096)
                    if not recv_data:
                        break
                    total_bytes += len(recv_data)
                    all_chunks.append(recv_data)
                    # Check pattern in accumulated data
                    combined = b"".join(all_chunks)
                    try:
                        text = combined.decode("utf-8", errors="replace")
                    except Exception:
                        text = combined.hex()
                    if pattern_re.search(text):
                        match_offset = total_bytes
                        time.sleep(0.3)
                        break
                except socket.timeout:
                    if match_offset >= 0:
                        break
                    continue
                except Exception:
                    break

            # Switch back to formatted mode
            try:
                sock.sendall(b"\x01FORMATTED\n")
            except Exception:
                pass
            sock.close()

            combined = b"".join(all_chunks)
            try:
                matched_text = combined.decode("utf-8", errors="replace")
            except Exception:
                matched_text = combined.hex()

            return {
                "type": "send_and_read_until_raw",
                "sent": {"data": data, "bytes": len(send_bytes), "hexSent": send_bytes.hex()},
                "pattern": pattern,
                "matched": match_offset >= 0,
                "data": combined.hex(),
                "dataAsciiPreview": matched_text[:500] if matched_text else "",
                "totalBytesRead": total_bytes,
                "timedOut": match_offset < 0,
            }
        except Exception as e:
            return {"type": "error", "message": f"Raw send_and_read_until failed: {e}"}
    else:
        # Formatted mode: reader thread + sender
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
    raw: bool = False,
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

        # Switch to raw mode if requested
        if raw:
            sock.sendall(b"\x01RAW\n")
            time.sleep(0.1)

        sock.settimeout(0.5)

        # Compile all patterns
        pattern_res = [re.compile(p, re.IGNORECASE) for p in patterns]

        if raw:
            # Raw mode: read binary data and search patterns
            all_chunks = []
            total_bytes = 0
            start = time.time()
            # Track matches: {pattern_index: [(byte_offset, chunk_index)]}
            matches = {i: [] for i in range(len(patterns))}

            while (time.time() - start) * 1000 < duration_ms:
                try:
                    data = sock.recv(4096)
                    if not data:
                        break
                    total_bytes += len(data)
                    all_chunks.append(data)
                    # Check patterns against ASCII representation
                    combined = b"".join(all_chunks)
                    try:
                        text = combined.decode("utf-8", errors="replace")
                    except Exception:
                        text = combined.hex()
                    for pi, pat_re in enumerate(pattern_res):
                        if pat_re.search(text):
                            matches[pi].append((total_bytes, len(all_chunks) - 1))
                except socket.timeout:
                    continue
                except Exception:
                    break

            # Switch back to formatted mode
            try:
                sock.sendall(b"\x01FORMATTED\n")
            except Exception:
                pass
            sock.close()

            combined = b"".join(all_chunks)
            try:
                text_preview = combined.decode("utf-8", errors="replace")
            except Exception:
                text_preview = combined.hex()

            total_matches = sum(len(v) for v in matches.values())
            result_matches = []
            for pi, pat in enumerate(patterns):
                for byte_offset, chunk_idx in matches[pi]:
                    result_matches.append({
                        "pattern": pat,
                        "byteOffset": byte_offset,
                        "matched": True,
                    })

            return {
                "type": "monitor_raw",
                "patterns": patterns,
                "totalMatches": total_matches,
                "matches": result_matches,
                "data": combined.hex(),
                "dataAsciiPreview": text_preview[:1000] if text_preview else "",
                "totalBytesRead": total_bytes,
                "elapsedMs": int((time.time() - start) * 1000),
                "summary": f"Raw monitored {total_bytes} bytes, found {total_matches} match(es) across {len(patterns)} pattern(s)",
            }
        else:
            # Formatted mode (existing logic)
            all_lines = []
            total_bytes = 0
            start = time.time()

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
def bbcom_mirror_read(port: int, host: str = "127.0.0.1", duration_ms: int = 5000, raw: bool = False) -> str:
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

    RAW MODE: When raw=True, receives raw serial bytes without any BBCom-added
    formatting (no direction tags, timestamps, delta time, or extra newlines).
    Data is returned as hex string. This provides a 1:1 mapping of serial port
    data, ideal for binary protocol analysis, firmware flashing, and precise
    byte-level operations.

    Args:
        port: Mirror server port number (e.g. 12345)
        host: Mirror server host address (default: 127.0.0.1)
        duration_ms: How long to read data in milliseconds (default: 5000)
        raw: If True, read raw serial bytes without formatting (default: False).
             Returns hex string of raw bytes for 1:1 serial data mapping.
    """
    result = _mirror_tcp_read(host, port, duration_ms, raw=raw)
    return json.dumps(result, indent=2)


@mcp.tool()
def bbcom_mirror_send(port: int, data: str, host: str = "127.0.0.1", raw: bool = False, hex_data: bool = False) -> str:
    """Send data through BBCom's mirror TCP server. The data will be forwarded
    to the serial port as a TX transmission. Use this to send commands to
    the serial device when you do NOT need to capture the response.

    IMPORTANT: If you need to send a command AND capture the response, use
    bbcom_mirror_send_and_read or bbcom_mirror_send_and_read_until instead.

    RAW MODE: When raw=True, sends exact bytes without any modification (no
    newline suffix added). Combined with hex_data=True, sends binary data
    decoded from hex string. This provides 1:1 mapping to serial port TX,
    ideal for binary protocol communication and firmware operations.

    Args:
        port: Mirror server port number (e.g. 12345)
        data: Data to send to the serial device
        host: Mirror server host address (default: 127.0.0.1)
        raw: If True, send raw bytes without modifications (no newline suffix).
             Use with hex_data=True for binary data (default: False)
        hex_data: If True, treat data as hex string (e.g. "48656c6c6f") and
                  decode to bytes before sending. Only effective when raw=True.
                  Example: "AA BB CC" or "AABBCC" sends bytes 0xAA, 0xBB, 0xCC
    """
    result = _mirror_tcp_send(host, port, data, raw=raw, hex_data=hex_data)
    return json.dumps(result, indent=2)


@mcp.tool()
def bbcom_mirror_send_and_read(
    port: int,
    data: str,
    host: str = "127.0.0.1",
    read_duration_ms: int = 5000,
    raw: bool = False,
    hex_data: bool = False,
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

    RAW MODE: When raw=True, sends and receives raw bytes without formatting.
    Response data is returned as hex string. Combined with hex_data=True for
    sending binary data. Provides 1:1 serial data mapping for protocol work.

    Args:
        port: Mirror server port number (e.g. 12345)
        data: Command to send to the serial device
        host: Mirror server host address (default: 127.0.0.1)
        read_duration_ms: How long to read response data in milliseconds (default: 5000)
        raw: If True, use raw mode for both send and receive (default: False)
        hex_data: If True, treat data as hex string for sending (default: False).
                  Only effective when raw=True.
    """
    result = _mirror_tcp_send_and_read(host, port, data, read_duration_ms, raw=raw, hex_data=hex_data)
    return json.dumps(result, indent=2)


@mcp.tool()
def bbcom_mirror_read_until(
    port: int,
    pattern: str,
    host: str = "127.0.0.1",
    timeout_ms: int = 30000,
    context_lines: int = 2,
    raw: bool = False,
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

    RAW MODE: When raw=True, reads raw serial bytes and searches pattern against
    the ASCII representation. Returns hex string of raw data. Useful for detecting
    patterns in binary data streams while preserving raw bytes.

    Args:
        port: Mirror server port number (e.g. 12345)
        pattern: Regex pattern to search for (case-insensitive)
        host: Mirror server host address (default: 127.0.0.1)
        timeout_ms: Maximum time to wait in milliseconds (default: 30000)
        context_lines: Number of lines before/after match for context (default: 2)
        raw: If True, read raw bytes without formatting (default: False)
    """
    result = _mirror_tcp_read_until(host, port, pattern, timeout_ms, context_lines, raw=raw)
    return json.dumps(result, indent=2)


@mcp.tool()
def bbcom_mirror_send_and_read_until(
    port: int,
    data: str,
    pattern: str,
    host: str = "127.0.0.1",
    timeout_ms: int = 30000,
    context_lines: int = 2,
    raw: bool = False,
    hex_data: bool = False,
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

    RAW MODE: When raw=True, sends raw bytes and reads raw response data.
    Pattern is searched against ASCII representation of accumulated raw bytes.
    Returns hex string of raw data. Combined with hex_data=True for binary protocols.

    Args:
        port: Mirror server port number (e.g. 12345)
        data: Command to send to the serial device
        pattern: Regex pattern to search for in response (case-insensitive)
        host: Mirror server host address (default: 127.0.0.1)
        timeout_ms: Maximum time to wait for pattern in milliseconds (default: 30000)
        context_lines: Number of lines before/after match for context (default: 2)
        raw: If True, use raw mode for both send and receive (default: False)
        hex_data: If True, treat data as hex string for sending (default: False).
                  Only effective when raw=True.
    """
    result = _mirror_tcp_send_and_read_until(
        host, port, data, pattern, timeout_ms, context_lines, raw=raw, hex_data=hex_data
    )
    return json.dumps(result, indent=2)


@mcp.tool()
def bbcom_mirror_monitor(
    port: int,
    patterns: str,
    host: str = "127.0.0.1",
    duration_ms: int = 30000,
    context_lines: int = 1,
    raw: bool = False,
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

    RAW MODE: When raw=True, monitors raw serial bytes. Patterns are searched
    against ASCII representation of accumulated raw data. Returns hex string
    of raw data plus match information. Useful for binary protocol monitoring.

    Args:
        port: Mirror server port number (e.g. 12345)
        patterns: Pipe-separated regex patterns to monitor (OR logic, case-insensitive).
                  Example: "HARDFAULT|FATAL ERROR|Watchdog"
        host: Mirror server host address (default: 127.0.0.1)
        duration_ms: How long to monitor in milliseconds (default: 30000)
        context_lines: Number of lines before/after each match for context (default: 1)
        raw: If True, monitor raw bytes without formatting (default: False)
    """
    pattern_list = [p.strip() for p in patterns.split("|") if p.strip()]
    if not pattern_list:
        return json.dumps(
            {"type": "error", "message": "No valid patterns provided"}, indent=2
        )

    result = _mirror_tcp_monitor(host, port, pattern_list, duration_ms, context_lines, raw=raw)
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


def _mirror_tcp_control(host: str, port: int, command: str, wait_seconds: float = 0.3) -> dict:
    """Send a control command through Mirror TCP control channel.

    Control commands use the \\x01 prefix to distinguish them from normal
    serial data. Format: \\x01<COMMAND>:<params>\\n

    Supported commands:
    - PING - Health check
    - SIGNALS:RTS=1,DTR=0 - Set RTS/DTR control signals (processed in Rust for precise timing)
    - BOOTLOAD - Enter ESP32 download mode (atomic RTS/DTR sequence with precise timing)
    - CONNECT:COM3,115200 - Connect serial port with baud rate
    - DISCONNECT - Disconnect serial port
    - CONFIG:baud=115200,data=8,parity=none,stop=1,flow=none - Set serial config
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect((host, port))

        control_data = f"\x01{command}\n".encode("utf-8")
        sock.sendall(control_data)

        # Wait for command to be processed
        time.sleep(wait_seconds)

        # Try to read any response (best effort)
        sock.settimeout(0.5)
        response = ""
        try:
            data = sock.recv(4096)
            if data:
                response = data.decode("utf-8", errors="replace").strip()
        except socket.timeout:
            pass

        sock.close()
        return {
            "type": "mirror_control",
            "command": command,
            "success": True,
            "message": response if response else "Control command sent",
        }

    except Exception as e:
        return {"type": "error", "message": f"Mirror control failed: {e}"}


def _get_mirror_connection() -> tuple[str, int] | None:
    """Get Mirror TCP host and port from runtime status.

    Returns (host, port) tuple if mirror is enabled, None otherwise.
    """
    status = _read_runtime_status()
    if not status.get("mirrorEnabled"):
        return None
    host = status.get("address") or "127.0.0.1"
    port = status.get("port")
    if not port:
        return None
    return (host, port)


@mcp.tool()
def bbcom_connect(port_name: str, baud_rate: int = 115200) -> str:
    """Connect to a serial port through BBCom's Mirror TCP control channel.
    The connection is made by sending a control command to the running BBCom
    application, which then opens the specified serial port.

    Prerequisites: BBCom must be running with Mirror mode enabled.

    After connecting, the serial port will be available for data transfer
    through the Mirror TCP connection. Use bbcom_mirror_send to send data
    and bbcom_mirror_read to receive data.

    Args:
        port_name: Serial port name (e.g. 'COM3', 'COM5', '/dev/ttyUSB0')
        baud_rate: Baud rate for the connection (default: 115200)
    """
    conn = _get_mirror_connection()
    if not conn:
        return json.dumps(
            {
                "type": "error",
                "message": "Mirror mode not enabled. Enable mirror mode in BBCom first.",
            },
            indent=2,
        )

    host, port = conn
    command = f"CONNECT:{port_name},{baud_rate}"
    result = _mirror_tcp_control(host, port, command)

    if result.get("type") == "error":
        return json.dumps(result, indent=2)

    # Wait for connection to establish and verify
    time.sleep(1.0)
    status = _read_runtime_status()
    if status.get("serialConnected"):
        return json.dumps(
            {
                "type": "connected",
                "portName": port_name,
                "baudRate": status.get("baudRate", baud_rate),
                "actualPort": status.get("serialPort", port_name),
                "message": f"Successfully connected to {status.get('serialPort', port_name)}",
            },
            indent=2,
        )
    else:
        return json.dumps(
            {
                "type": "error",
                "message": f"Connection command sent, but serial port is not connected. "
                f"The port '{port_name}' may not exist or may be in use.",
            },
            indent=2,
        )


@mcp.tool()
def bbcom_disconnect() -> str:
    """Disconnect the current serial port through BBCom's Mirror TCP control
    channel. Sends a DISCONNECT control command to BBCom.

    Prerequisites: BBCom must be running with Mirror mode enabled and a
    serial port must be currently connected.

    Returns confirmation that the port was disconnected.
    """
    conn = _get_mirror_connection()
    if not conn:
        return json.dumps(
            {
                "type": "error",
                "message": "Mirror mode not enabled. Enable mirror mode in BBCom first.",
            },
            indent=2,
        )

    host, port = conn

    # Check current status
    status = _read_runtime_status()
    if not status.get("serialConnected"):
        return json.dumps(
            {"type": "disconnected", "message": "No serial port currently connected"},
            indent=2,
        )

    result = _mirror_tcp_control(host, port, "DISCONNECT")

    if result.get("type") == "error":
        return json.dumps(result, indent=2)

    # Wait and verify disconnection
    time.sleep(0.5)
    status = _read_runtime_status()
    if not status.get("serialConnected"):
        return json.dumps(
            {"type": "disconnected", "message": "Serial port disconnected successfully"},
            indent=2,
        )
    else:
        return json.dumps(
            {
                "type": "error",
                "message": f"Disconnect command sent, but port {status.get('serialPort')} is still connected",
            },
            indent=2,
        )


@mcp.tool()
def bbcom_set_signals(rts: bool | None = None, dtr: bool | None = None) -> str:
    """Set RTS (Request To Send) and DTR (Data Terminal Ready) control signals
    on the currently connected serial port. This is essential for entering
    ESP32 download mode, which requires precise RTS/DTR timing.

    NOTE: For entering ESP32 download mode, prefer bbcom_enter_bootloader which
    executes the entire RTS/DTR sequence atomically with precise timing on the
    BBCom server side.

    ESP32 Download Mode Sequence:
    1. Set RTS=1, DTR=0 (asserts RESET via RTS, releases GPIO0 via DTR)
    2. Set RTS=0, DTR=1 (releases RESET, asserts GPIO0 via DTR → boot mode)
    3. Set RTS=0, DTR=0 (release both → chip runs in download mode)

    Prerequisites: BBCom must be running with Mirror mode enabled and a
    serial port must be currently connected.

    Args:
        rts: Set RTS signal to true (high) or false (low). None = no change.
        dtr: Set DTR signal to true (high) or false (low). None = no change.
    """
    if rts is None and dtr is None:
        return json.dumps(
            {"type": "error", "message": "At least one of rts or dtr must be specified"},
            indent=2,
        )

    conn = _get_mirror_connection()
    if not conn:
        return json.dumps(
            {
                "type": "error",
                "message": "Mirror mode not enabled. Enable mirror mode in BBCom first.",
            },
            indent=2,
        )

    host, port = conn

    # Check if serial is connected
    status = _read_runtime_status()
    if not status.get("serialConnected"):
        return json.dumps(
            {
                "type": "error",
                "message": "No serial port connected. Connect a port first using bbcom_connect.",
            },
            indent=2,
        )

    # Build SIGNALS command
    parts = []
    if rts is not None:
        parts.append(f"RTS={1 if rts else 0}")
    if dtr is not None:
        parts.append(f"DTR={1 if dtr else 0}")
    command = f"SIGNALS:{','.join(parts)}"

    result = _mirror_tcp_control(host, port, command)

    if result.get("type") == "error":
        return json.dumps(result, indent=2)

    return json.dumps(
        {
            "type": "signals_set",
            "rts": rts,
            "dtr": dtr,
            "message": f"Control signals updated: {', '.join(parts)}",
        },
        indent=2,
    )


@mcp.tool()
def bbcom_enter_bootloader(
    read_duration_ms: int = 3000,
    raw: bool = False,
) -> str:
    """Enter ESP32 download mode and capture bootloader output atomically.

    Starts a reader connection FIRST, then sends the BOOTLOAD command, ensuring
    no bootloader output is missed. This is the preferred way to enter ESP32
    bootloader mode because:
    1. The entire RTS/DTR signal sequence is handled atomically in the BBCom
       Rust backend with precise timing (impossible via separate SIGNALS calls)
    2. The reader is connected before the reset, so all bootloader output is
       captured (impossible via separate enter_bootloader + mirror_read calls)

    The sequence executed on the server:
    1. RTS=1, DTR=0  (assert RESET via RTS, release GPIO0)
    2. Wait 100ms
    3. RTS=0, DTR=1  (release RESET, assert GPIO0 → boot mode)
    4. Wait 50ms
    5. RTS=0, DTR=0  (release both, chip runs in download mode)

    Prerequisites: BBCom must be running with Mirror mode enabled and a
    serial port must be currently connected at 115200 baud.

    Args:
        read_duration_ms: How long to read bootloader output in milliseconds
                          (default: 3000). ESP32 bootloader output arrives
                          within ~500ms of reset.
        raw: If True, read raw serial bytes without formatting (default: False).
             Returns hex string of raw bytes for binary protocol analysis.
    """
    conn = _get_mirror_connection()
    if not conn:
        return json.dumps(
            {
                "type": "error",
                "message": "Mirror mode not enabled. Enable mirror mode in BBCom first.",
            },
            indent=2,
        )

    host, port = conn

    # Check if serial is connected
    status = _read_runtime_status()
    if not status.get("serialConnected"):
        return json.dumps(
            {
                "type": "error",
                "message": "No serial port connected. Connect a port first using bbcom_connect.",
            },
            indent=2,
        )

    # Pattern: start reader FIRST, then send BOOTLOAD, then collect response
    # This ensures we don't miss the bootloader output that arrives immediately
    # after the RTS/DTR sequence resets the chip.
    if raw:
        # Raw mode: single connection approach
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5.0)
            sock.connect((host, port))

            # Switch to raw mode
            sock.sendall(b"\x01RAW\n")
            time.sleep(0.1)

            # Send BOOTLOAD command (processed atomically in Rust backend)
            sock.sendall(b"\x01BOOTLOAD\n")

            # Read raw bootloader output
            chunks = []
            total_bytes = 0
            start = time.time()

            while (time.time() - start) * 1000 < read_duration_ms:
                try:
                    recv_data = sock.recv(4096)
                    if not recv_data:
                        break
                    total_bytes += len(recv_data)
                    chunks.append(recv_data)
                except socket.timeout:
                    continue
                except Exception:
                    break

            # Switch back to formatted mode
            try:
                sock.sendall(b"\x01FORMATTED\n")
            except Exception:
                pass
            sock.close()

            raw_response = b"".join(chunks)
            return json.dumps(
                {
                    "type": "bootloader_entered_raw",
                    "message": "ESP32 download mode sequence executed.",
                    "output": {
                        "data": raw_response.hex(),
                        "bytes": total_bytes,
                    },
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps(
                {"type": "error", "message": f"Bootloader entry failed: {e}"}, indent=2
            )
    else:
        # Formatted mode: separate reader and sender threads
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
            return json.dumps(
                {"type": "error", "message": "Reader connection timed out"}, indent=2
            )

        if reader_error:
            return json.dumps(
                {"type": "error", "message": f"Reader connection failed: {reader_error}"}, indent=2
            )

        # Now send BOOTLOAD command via control channel
        result = _mirror_tcp_control(host, port, "BOOTLOAD", wait_seconds=0.2)

        if result.get("type") == "error":
            reader_thread.join(timeout=read_duration_ms / 1000 + 1)
            return json.dumps(result, indent=2)

        # Wait for reader to finish collecting bootloader output
        reader_thread.join(timeout=read_duration_ms / 1000 + 1)

        return json.dumps(
            {
                "type": "bootloader_entered",
                "message": "ESP32 download mode sequence executed.",
                "output": {
                    "lines": reader_lines,
                    "bytes": reader_bytes,
                },
            },
            indent=2,
        )


@mcp.tool()
def bbcom_set_serial_config(
    baud_rate: int | None = None,
    data_bits: int | None = None,
    parity: str | None = None,
    stop_bits: int | None = None,
    flow_control: str | None = None,
) -> str:
    """Configure serial port settings through BBCom's Mirror TCP control channel.
    Changes take effect on the next connection. Use this before bbcom_connect
    to ensure the correct settings are applied.

    Supported values:
    - baud_rate: 9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600
    - data_bits: 5, 6, 7, 8
    - parity: 'none', 'odd', 'even'
    - stop_bits: 1, 2
    - flow_control: 'none', 'software', 'hardware'

    Prerequisites: BBCom must be running with Mirror mode enabled.

    Args:
        baud_rate: Baud rate (e.g. 115200)
        data_bits: Data bits (5, 6, 7, or 8)
        parity: Parity check mode ('none', 'odd', or 'even')
        stop_bits: Stop bits (1 or 2)
        flow_control: Flow control mode ('none', 'software', or 'hardware')
    """
    conn = _get_mirror_connection()
    if not conn:
        return json.dumps(
            {
                "type": "error",
                "message": "Mirror mode not enabled. Enable mirror mode in BBCom first.",
            },
            indent=2,
        )

    host, port = conn

    # Build CONFIG command
    parts = []
    if baud_rate is not None:
        parts.append(f"baud={baud_rate}")
    if data_bits is not None:
        parts.append(f"data={data_bits}")
    if parity is not None:
        parts.append(f"parity={parity}")
    if stop_bits is not None:
        parts.append(f"stop={stop_bits}")
    if flow_control is not None:
        parts.append(f"flow={flow_control}")

    if not parts:
        return json.dumps(
            {"type": "error", "message": "At least one config parameter must be specified"},
            indent=2,
        )

    command = f"CONFIG:{','.join(parts)}"
    result = _mirror_tcp_control(host, port, command)

    if result.get("type") == "error":
        return json.dumps(result, indent=2)

    return json.dumps(
        {
            "type": "config_updated",
            "settings": dict(p.split("=") for p in parts),
            "message": f"Serial config updated: {', '.join(parts)}",
        },
        indent=2,
    )


# ---------------------------------------------------------------------------
# JSON RPC over the mirror control channel (BBCom >= 1.8.7)
# ---------------------------------------------------------------------------

def _mirror_rpc(command: str, args: dict | None = None, timeout_s: float = 15.0) -> dict:
    """Send a JSON RPC request over the mirror control channel and wait for the
    matching response.

    Request:  \\x01RPC {"id":"...","cmd":"...","args":{...}}
    Response: \\x01RPCRESP {"id":"...","ok":true,"result":...}   (or ok=false+error)

    Unlike _mirror_tcp_control, this waits for an explicit response with a
    matching id, so success/failure is known instead of assumed. Only
    allowlisted commands are accepted by the BBCom backend (see
    src-tauri/src/mirror_rpc.rs).
    """
    conn = _get_mirror_connection()
    if not conn:
        return {
            "type": "error",
            "message": "Mirror mode not enabled. Enable mirror mode in BBCom first.",
        }
    host, port = conn

    rpc_id = f"{time.time_ns()}"
    payload = json.dumps({"id": rpc_id, "cmd": command, "args": args or {}})
    prefix = b"\x01RPCRESP "
    try:
        with socket.create_connection((host, port), timeout=5) as sock:
            sock.sendall(f"\x01RPC {payload}\n".encode("utf-8"))
            sock.settimeout(1.0)
            deadline = time.time() + timeout_s
            buf = b""
            while time.time() < deadline:
                try:
                    chunk = sock.recv(65536)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                buf += chunk
                while True:
                    nl = buf.find(b"\n")
                    if nl < 0:
                        break
                    line = buf[:nl]
                    buf = buf[nl + 1:]
                    if not line.startswith(prefix):
                        continue  # broadcast/log line — ignore
                    try:
                        resp = json.loads(line[len(prefix):].decode("utf-8"))
                    except Exception:
                        continue
                    if resp.get("id") == rpc_id:
                        return {"type": "rpc", "rpc": resp}
            return {
                "type": "error",
                "message": (
                    f"RPC timeout ({timeout_s:.0f}s) waiting for response to "
                    f"'{command}'. Is BBCom >= 1.8.7 running with mirror enabled?"
                ),
            }
    except Exception as e:
        return {"type": "error", "message": f"Mirror RPC failed: {e}"}


def _rpc_result_to_json(result: dict, indent: int = 2) -> str:
    """Format an _mirror_rpc() result: unwrap ok/result, or pass through the error."""
    if result.get("type") == "error":
        return json.dumps(result, indent=indent)
    rpc = result.get("rpc", {})
    if rpc.get("ok"):
        return json.dumps({"type": "rpc_result", "result": rpc.get("result")}, indent=indent)
    return json.dumps(
        {"type": "error", "message": rpc.get("error", "RPC failed")}, indent=indent
    )


@mcp.tool()
def bbcom_rpc(command: str, args_json: str = "{}") -> str:
    """Generic JSON RPC over the BBCom mirror control channel (BBCom >= 1.8.7).

    Calls an allowlisted BBCom backend command synchronously and returns its
    result. Allowlist (see also the dedicated tools which wrap most of these):
    - ping, get_connection_status, get_ports
    - traffic_get, traffic_deltas
    - bblog_get_status, bblog_get_stats, bblog_get_sync_status
    - lclog_dump_start, lclog_dump_get_state, lclog_dump_cancel, lclog_dump_take_result

    Args:
        command: Command name (see allowlist above)
        args_json: JSON object with arguments (most commands take none)

    Returns:
        JSON {"type":"rpc_result","result":...} on success, or
        {"type":"error","message":...} on failure.
    """
    try:
        args = json.loads(args_json) if args_json and args_json.strip() else {}
    except json.JSONDecodeError as e:
        return json.dumps({"type": "error", "message": f"Invalid args_json: {e}"}, indent=2)
    if not isinstance(args, dict):
        return json.dumps({"type": "error", "message": "args_json must be a JSON object"}, indent=2)
    return _rpc_result_to_json(_mirror_rpc(command, args))


@mcp.tool()
def bbcom_bblog_status() -> str:
    """Get BBLog decoder status: enabled, sync state, build id and counters.

    Requires BBCom >= 1.8.7 running with mirror enabled. Use this to check
    whether the device logs are currently decodable (synced) before decoding
    or dumping device logs.
    """
    status = _mirror_rpc("bblog_get_status", {})
    stats = _mirror_rpc("bblog_get_stats", {})
    if status.get("type") == "error":
        return json.dumps(status, indent=2)
    rpc_status = status.get("rpc", {})
    counters = {}
    if stats.get("type") == "rpc" and stats.get("rpc", {}).get("ok"):
        counters = stats["rpc"].get("result", {}).get("counters", {})
    return json.dumps(
        {
            "type": "rpc_result",
            "status": rpc_status.get("result") if rpc_status.get("ok") else None,
            "error": rpc_status.get("error") if not rpc_status.get("ok") else None,
            "counters": counters,
        },
        indent=2,
    )


@mcp.tool()
def bbcom_traffic() -> str:
    """Get serial traffic counters: cumulative RX/TX bytes and per-second deltas.

    Requires BBCom >= 1.8.7 running with mirror enabled. Useful to check
    whether the device is actually sending data and at what rate.
    """
    snap = _mirror_rpc("traffic_get", {})
    deltas = _mirror_rpc("traffic_deltas", {})
    if snap.get("type") == "error":
        return json.dumps(snap, indent=2)
    result: dict = {}
    if snap.get("rpc", {}).get("ok"):
        result["totals"] = snap["rpc"].get("result")
    else:
        result["error"] = snap.get("rpc", {}).get("error", "traffic_get failed")
    if deltas.get("rpc", {}).get("ok"):
        result["deltas_per_second"] = deltas["rpc"].get("result")
    return json.dumps({"type": "rpc_result", **result}, indent=2)


@mcp.tool()
def bbcom_bblog_dump_start(
    save_raw: bool = False,
    wait: bool = True,
    timeout_s: int = 300,
    output_path: str = "",
) -> str:
    """Dump the device's LCLog/BBL2 ring and decode it to a .txt file.

    One-stop tool: starts the dump on the device, optionally waits for it to
    finish (polling progress), then writes the decoded log text to a file and
    returns the file path so it can be read and analyzed.

    Prerequisites (all checked by BBCom):
    - BBCom >= 1.8.7 running with mirror enabled
    - Serial port connected
    - BBLog decoding enabled (Enable BBLog Decoding) and a token table loaded
    - Device firmware built with lclog storage (CONFIG_LCLOG_BACKEND_STORAGE)

    Args:
        save_raw: Also return the raw BBL2 image as a .bin file (default False)
        wait: Wait for completion and write the output file (default True).
              If False, only starts the dump; poll with bbcom_bblog_dump_status
              and fetch with bbcom_bblog_dump_take_result.
        timeout_s: Max seconds to wait when wait=True (default 300)
        output_path: Where to write the .txt (default:
                     %LOCALAPPDATA%/bbcom/dumps/<suggested filename>)

    Returns:
        JSON with the dump result file path(s) and statistics, or progress
        info when wait=False.
    """
    started = _mirror_rpc("lclog_dump_start", {"save_raw": save_raw}, timeout_s=10)
    if started.get("type") == "error":
        return json.dumps(started, indent=2)
    rpc = started.get("rpc", {})
    if not rpc.get("ok"):
        return json.dumps(
            {"type": "error", "message": rpc.get("error", "lclog_dump_start failed")}, indent=2
        )

    if not wait:
        return json.dumps(
            {"type": "rpc_result", "started": True, "message": "Dump started. Poll with bbcom_bblog_dump_status."},
            indent=2,
        )

    # Poll until done / failed / cancelled
    deadline = time.time() + max(30, timeout_s)
    last_progress = {}
    while time.time() < deadline:
        time.sleep(2)
        state = _mirror_rpc("lclog_dump_get_state", {}, timeout_s=10)
        if state.get("type") == "error":
            return json.dumps(state, indent=2)
        st = state.get("rpc", {}).get("result", {})
        last_progress = st
        phase = st.get("phase", "")
        if phase in ("done", "failed", "cancelled"):
            break
        # Emit compact progress info for the caller log
        last_progress = st

    if last_progress.get("phase") not in ("done",):
        return json.dumps(
            {"type": "error", "phase": last_progress.get("phase", "unknown"),
             "progress": last_progress,
             "message": last_progress.get("error") or f"Dump did not complete within {timeout_s}s"},
            indent=2,
        )

    return _bblog_dump_write_output(output_path)


def _bblog_dump_write_output(output_path: str) -> str:
    """Fetch the completed dump result via RPC and write it to file(s)."""
    taken = _mirror_rpc("lclog_dump_take_result", {}, timeout_s=60)
    if taken.get("type") == "error":
        return json.dumps(taken, indent=2)
    rpc = taken.get("rpc", {})
    if not rpc.get("ok"):
        return json.dumps(
            {"type": "error", "message": rpc.get("error", "lclog_dump_take_result failed")}, indent=2
        )
    result = rpc.get("result", {})
    text = result.get("text", "")
    raw_hex = result.get("raw_hex")
    stats = result.get("stats")
    suggested = result.get("suggested_filename") or "lclog_dump.txt"

    if output_path:
        out_file = Path(output_path)
    else:
        base_dir = Path(os.environ.get("LOCALAPPDATA", "")) / "bbcom" / "dumps"
        base_dir.mkdir(parents=True, exist_ok=True)
        out_file = base_dir / suggested

    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(text, encoding="utf-8")

    written: dict = {"text_file": str(out_file), "records_stats": stats}
    if raw_hex:
        bin_path = (
            out_file.with_suffix(".bin")
            if out_file.suffix.lower() == ".txt"
            else out_file.parent / (out_file.name + ".bin")
        )
        bin_path.write_bytes(bytes.fromhex(raw_hex))
        written["raw_bin_file"] = str(bin_path)

    return json.dumps({"type": "rpc_result", **written}, indent=2)


@mcp.tool()
def bbcom_bblog_dump_status() -> str:
    """Get the current LCLog dump session state (phase, progress, counters).

    Requires BBCom >= 1.8.7. Use after bbcom_bblog_dump_start(wait=False) to
    poll progress: phase is one of idle/summary/dumping/decoding/done/failed/
    cancelled; idx/blocks give the current block progress.
    """
    return _rpc_result_to_json(_mirror_rpc("lclog_dump_get_state", {}, timeout_s=10))


@mcp.tool()
def bbcom_bblog_dump_cancel() -> str:
    """Cancel a running LCLog dump session (BBCom >= 1.8.7)."""
    return _rpc_result_to_json(_mirror_rpc("lclog_dump_cancel", {}, timeout_s=10))


@mcp.tool()
def bbcom_bblog_dump_take_result(output_path: str = "") -> str:
    """Fetch the decoded result of a completed LCLog dump and write it to a file.

    Requires BBCom >= 1.8.7 and a finished dump session (phase 'done', see
    bbcom_bblog_dump_status). The result is cleared from BBCom by this call.

    Args:
        output_path: Where to write the .txt (default:
                     %LOCALAPPDATA%/bbcom/dumps/<suggested filename>)
    """
    return _bblog_dump_write_output(output_path)


def main():
    """Entry point for the MCP server (used by pyproject.toml script)."""
    mcp.run()


if __name__ == "__main__":
    main()
