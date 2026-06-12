#!/usr/bin/env python3
"""
BBCom MCP Server - Model Context Protocol server for BBCom serial communication tool.

Provides LLMs with the ability to:
- Query BBCom mirror status and serial configuration
- Read real-time serial data via mirror TCP connection
- Send commands to serial devices via mirror TCP connection
- Control serial port connection (connect/disconnect)

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
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

# BBCom executable name
BBCOM_EXE = "bbcom.exe" if sys.platform == "win32" else "bbcom"

mcp = FastMCP("bbcom")


def _find_bbcom_exe() -> str | None:
    """Find BBCom executable in common locations."""
    # Check PATH first
    for path_dir in os.environ.get("PATH", "").split(os.pathsep):
        exe_path = Path(path_dir) / BBCOM_EXE
        if exe_path.exists():
            return str(exe_path)

    # Check LOCALAPPDATA (MSIX install)
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        msix_paths = [
            Path(local_app_data) / "Programs" / "BBCom" / BBCOM_EXE,
            Path(local_app_data) / "Microsoft" / "WindowsApps" / BBCOM_EXE,
        ]
        for p in msix_paths:
            if p.exists():
                return str(p)

    # Check BBCOM_EXE_PATH environment variable (for custom install paths)
    custom_path = os.environ.get("BBCOM_EXE_PATH", "")
    if custom_path and Path(custom_path).exists():
        return custom_path

    return None


def _run_cli_command(*args: str) -> dict:
    """Run a BBCom CLI command and return parsed JSON result."""
    bbcom = _find_bbcom_exe()
    if not bbcom:
        return {"type": "error", "message": "BBCom executable not found. Is BBCom installed?"}

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
    with bbcom_mirror_read and bbcom_mirror_send."""
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
    content. This is the primary way for LLMs to access live serial data.

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
    the serial device. The data should be a plain text string.

    Args:
        port: Mirror server port number (e.g. 12345)
        data: Data to send to the serial device
        host: Mirror server host address (default: 127.0.0.1)
    """
    result = _mirror_tcp_send(host, port, data)
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


if __name__ == "__main__":
    mcp.run()
