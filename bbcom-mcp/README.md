# BBCom MCP Server

MCP (Model Context Protocol) server for [BBCom](https://github.com/user/bbcom) serial communication tool. Enables LLMs (like Claude, GPT, etc.) to access real-time serial data and control serial devices through BBCom's mirror mode.

## Features

- **Query Status**: Check if BBCom is running, mirror mode status, serial connection info
- **Read Serial Data**: Connect to mirror TCP port and read real-time serial data
- **Send Commands**: Send data to serial devices through the mirror TCP port
- **Control Serial**: List ports, get/set configuration (baud rate, display mode, etc.)

## Prerequisites

- [BBCom](https://github.com/BBComTeam/BBCom) v1.4.9+ installed and running
- Python 3.10+
- `mcp` package installed

## Installation

```bash
pip install bbcom-mcp
```

Or install from source:

```bash
git clone https://github.com/BBComTeam/BBCom.git
cd bbcom-mcp
pip install -e .
```

## Configuration

### Claude Desktop

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "bbcom": {
      "command": "python",
      "args": ["-m", "bbcom_mcp_server"]
    }
  }
}
```

### Cursor

Add to your `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "bbcom": {
      "command": "python",
      "args": ["-m", "bbcom_mcp_server"]
    }
  }
}
```

### VS Code (with GitHub Copilot)

Add to your VS Code settings:

```json
{
  "mcp.servers": {
    "bbcom": {
      "command": "python",
      "args": ["-m", "bbcom_mcp_server"]
    }
  }
}
```

## Usage

### Step 1: Enable Mirror in BBCom

1. Open BBCom
2. Go to Terminal mode
3. Select TCP type, Server role
4. Set listen address (e.g., `127.0.0.1`) and port (e.g., `12345`)
5. Check "Enable Mirror" checkbox
6. Click Connect

### Step 2: LLM Auto-Discovery

Once the MCP server is configured, the LLM can:

1. Call `bbcom_status` to check if BBCom mirror is active
2. Call `bbcom_mirror_read` with the discovered port to read serial data
3. Call `bbcom_mirror_send` to send commands to the serial device

### Example LLM Workflow

```
LLM: Let me check BBCom's status...
→ bbcom_status() → {"mirrorEnabled": true, "address": "127.0.0.1", "port": 12345, ...}

LLM: Mirror is active on port 12345. Let me read some serial data...
→ bbcom_mirror_read(port=12345, duration_ms=3000) → {"lines": ["[RX] [14:30:01] Hello from device"], ...}

LLM: I see the device is sending "Hello". Let me send a response...
→ bbcom_mirror_send(port=12345, data="ACK") → {"bytes": 4}
```

## Available Tools

| Tool | Description |
|------|-------------|
| `bbcom_status` | Get overall BBCom status (mirror, serial, terminal) |
| `bbcom_mirror_status` | Get detailed mirror status |
| `bbcom_serial_status` | Get serial port connection status |
| `bbcom_mirror_read` | Read real-time data from mirror TCP port |
| `bbcom_mirror_send` | Send data through mirror TCP port to serial device |
| `bbcom_list_ports` | List available serial ports |
| `bbcom_get_config` | Get BBCom configuration |
| `bbcom_set_baud_rate` | Set serial baud rate |
| `bbcom_set_display_mode` | Set display mode (ascii/hex) |

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

- **MCP Server** communicates with BBCom through two channels:
  1. **TCP connection**: For real-time data read/write via mirror mode
  2. **CLI commands**: For status queries and configuration (`bbcom.exe --test`)
  3. **Status file**: Direct file read for fast status queries (`%LOCALAPPDATA%\bbcom\runtime_status.json`)

## CLI Commands Reference

The MCP server wraps these BBCom CLI commands:

```bash
bbcom.exe --test mirror-status     # Mirror status
bbcom.exe --test serial-status     # Serial status
bbcom.exe --test mirror-read <host> <port> [duration_ms]  # Read mirror data
bbcom.exe --test mirror-send <host> <port> <data>         # Send via mirror
bbcom.exe --test list-ports        # List serial ports
bbcom.exe --test get-config        # Get configuration
bbcom.exe --test set-baud-rate <baud>   # Set baud rate
bbcom.exe --test set-display <mode>     # Set display mode
```

## License

MIT
