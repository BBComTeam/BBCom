# BBCom MCP Server

MCP (Model Context Protocol) server for [BBCom](https://github.com/BBComTeam/BBCom) serial communication tool. Enables LLMs (like Claude, GPT, etc.) to access real-time serial data and control serial devices through BBCom's mirror mode.

## Features

- **Query Status**: Check if BBCom is running, mirror mode status, serial connection info
- **Read Serial Data**: Connect to mirror TCP port and read real-time serial data
- **Send Commands**: Send data to serial devices through the mirror TCP port
- **Atomic Send+Read**: Send command and capture response in one operation (avoids missed data)
- **Pattern Matching**: Wait for specific patterns (HARDFAULT, FATAL ERROR, boot complete, etc.)
- **Multi-Pattern Monitoring**: Watch for multiple error/event patterns simultaneously
- **Control Serial**: List ports, get/set configuration (baud rate, display mode, etc.)

## Prerequisites

- [BBCom](https://github.com/BBComTeam/BBCom) v1.4.9+ installed and running
- [uv](https://docs.astral.sh/uv/getting-started/installation/) (recommended) **or** Python 3.10+ with pip

## Installation

### Option 1: Using uv (Recommended)

No Python or dependency setup needed. Just install [uv](https://docs.astral.sh/uv/getting-started/installation/) and configure your MCP client.

### Option 2: Using Python directly

```bash
pip install mcp
```

Then point your MCP client to the `bbcom_mcp_server.py` file.

## Configuration

### Claude Desktop / Cursor / CodeBuddy

Using **uv** (recommended — auto-manages dependencies):

```json
{
  "mcpServers": {
    "bbcom": {
      "type": "stdio",
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/bbcom-mcp",
        "run",
        "bbcom-mcp"
      ]
    }
  }
}
```

Using **Python** directly:

```json
{
  "mcpServers": {
    "bbcom": {
      "type": "stdio",
      "command": "python",
      "args": ["/path/to/bbcom-mcp/bbcom_mcp_server.py"]
    }
  }
}
```

### Optional: Custom BBCom Path

If BBCom is not found automatically, set the `BBCOM_EXE_PATH` environment variable:

```json
{
  "mcpServers": {
    "bbcom": {
      "type": "stdio",
      "command": "uv",
      "args": ["--directory", "/path/to/bbcom-mcp", "run", "bbcom-mcp"],
      "env": {
        "BBCOM_EXE_PATH": "C:/path/to/bbcom.exe"
      }
    }
  }
}
```

The server automatically searches for `bbcom.exe` in:
1. `BBCOM_EXE_PATH` environment variable
2. System `PATH`
3. Windows registry (Uninstall keys)
4. Common install paths (`Program Files`, `LOCALAPPDATA`, etc.)
5. Same directory as `runtime_status.json`

## Usage

### Step 1: Enable Mirror in BBCom

1. Open BBCom
2. Go to Terminal mode
3. Select TCP type, Server role
4. Set listen address (e.g., `127.0.0.1`) and port (e.g., `5000`)
5. Check "Enable Mirror" checkbox
6. Click Connect

### Step 2: LLM Auto-Discovery

Once the MCP server is configured, the LLM can:

1. Call `bbcom_status` to check if BBCom mirror is active
2. Call `bbcom_mirror_read` with the discovered port to read serial data
3. Call `bbcom_mirror_send_and_read` to send commands and capture responses
4. Call `bbcom_mirror_read_until` to wait for specific patterns

## Available Tools

### Status & Configuration

| Tool | Description |
|------|-------------|
| `bbcom_status` | Get overall BBCom status (mirror, serial, terminal) |
| `bbcom_mirror_status` | Get detailed mirror status (address, port, clients) |
| `bbcom_serial_status` | Get serial port connection status |
| `bbcom_list_ports` | List available serial ports |
| `bbcom_get_config` | Get BBCom configuration |
| `bbcom_set_baud_rate` | Set serial baud rate |
| `bbcom_set_display_mode` | Set display mode (ascii/hex) |

### Mirror Data Operations

| Tool | Description |
|------|-------------|
| `bbcom_mirror_read` | Read real-time data from mirror TCP port |
| `bbcom_mirror_send` | Send data through mirror TCP port (fire-and-forget) |
| `bbcom_mirror_send_and_read` | Send command AND capture response atomically |
| `bbcom_mirror_read_until` | Read until pattern matched (e.g. HARDFAULT) |
| `bbcom_mirror_send_and_read_until` | Send command, read until pattern in response |
| `bbcom_mirror_monitor` | Monitor for multiple patterns, return only matches |

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐
│  LLM/Claude │────→│  MCP Server  │────→│  BBCom CLI   │
│             │     │  (Python)    │     │  (--test)    │
└─────────────┘     └──────┬───────┘     └──────────────┘
                           │                     │
                    TCP connection         Status file
                           │             (runtime_status.json)
                           ▼
                  ┌──────────────────┐
                  │   BBCom Mirror   │
                  │   TCP Server     │
                  │  (127.0.0.1:port)│
                  └────────┬─────────┘
                           │
                    Serial Port
                           │
                  ┌────────▼─────────┐
                  │   Serial Device   │
                  │  (MCU, GPS, etc.) │
                  └──────────────────┘
```

The MCP server communicates with BBCom through three channels:
1. **TCP connection**: Real-time data read/write via mirror mode
2. **CLI commands**: Status queries and configuration (`bbcom.exe --test`)
3. **Status file**: Fast status queries (`%LOCALAPPDATA%\bbcom\runtime_status.json`)

## License

MIT
