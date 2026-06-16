# BBCom MCP Server 安装指南

## 前置要求

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) 包管理器
- [BBCom](https://github.com/BBComTeam/BBCom) 串口通信工具（需运行中以使用完整功能）

## 安装运行

```bash
# 使用 uvx 直接运行（推荐）
uvx --directory . bbcom-mcp

# 或使用 uv run
uv --directory . run bbcom-mcp
```

## CodeBuddy 配置

在 `~/.codebuddy/mcp.json` 中添加：

```json
{
  "mcpServers": {
    "bbcom": {
      "type": "stdio",
      "command": "uv",
      "args": ["--directory", "<bbcom-mcp-path>", "run", "bbcom-mcp"],
      "description": "BBCom Serial Communication MCP Server"
    }
  }
}
```

将 `<bbcom-mcp-path>` 替换为 bbcom-mcp 目录的实际路径。

## 提供的工具

| 工具 | 说明 |
|------|------|
| `bbcom_version` | 获取 MCP 服务器版本 |
| `bbcom_status` | 查询 BBCom 连接状态 |
| `bbcom_list_ports` | 列出可用串口 |
| `bbcom_get_config` | 获取当前配置 |
| `bbcom_set_baud_rate` | 设置波特率 |
| `bbcom_set_display_mode` | 设置显示模式 (ASCII/HEX) |
| `bbcom_connect` | 连接串口（通过 Mirror TCP 控制命令） |
| `bbcom_disconnect` | 断开串口连接 |
| `bbcom_set_signals` | 设置 RTS/DTR 控制信号 |
| `bbcom_set_serial_config` | 设置完整串口配置（数据位/校验/停止位/流控） |
| `bbcom_mirror_status` | 查询镜像模式状态 |
| `bbcom_mirror_read` | 读取镜像数据（支持 raw 模式获取原始串口字节） |
| `bbcom_mirror_send` | 发送数据到串口（支持 raw 模式发送精确字节） |
| `bbcom_mirror_send_and_read` | 发送并读取响应（支持 raw 模式） |
| `bbcom_mirror_read_until` | 读取直到匹配条件（支持 raw 模式） |
| `bbcom_mirror_send_and_read_until` | 发送并读取直到匹配条件（支持 raw 模式） |
| `bbcom_mirror_monitor` | 监控串口数据流（支持 raw 模式） |
| `bbcom_serial_status` | 查询串口详细状态 |

## Raw 模式

所有 Mirror 读写工具都支持 `raw` 参数。当 `raw=True` 时：

- **读取**：返回原始串口字节（hex 格式），不含 BBCom 添加的方向标签、时间戳、delta time 或额外换行符。实现串口到 TCP Mirror 的 1:1 映射。
- **发送**：发送精确字节，不添加换行符后缀。配合 `hex_data=True` 可发送二进制数据（如 `"AA BB CC"` 发送字节 0xAA, 0xBB, 0xCC）。

### Raw 模式典型场景

- **二进制协议通信**：发送/接收精确的二进制帧
- **固件烧录**：通过串口发送固件数据块
- **协议分析**：捕获原始字节流进行分析
- **ESP32 操作**：配合 `bbcom_set_signals` 实现下载模式切换和固件烧录

## 验证安装

启动后可使用 `bbcom_version` 工具验证：

```
> bbcom_version
{
  "name": "bbcom-mcp",
  "version": "1.0.0"
}
```
