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
| `bbcom_mirror_status` | 查询镜像模式状态 |
| `bbcom_mirror_read` | 读取镜像数据 |
| `bbcom_mirror_send` | 发送数据到串口 |
| `bbcom_mirror_send_and_read` | 发送并读取响应 |
| `bbcom_mirror_read_until` | 读取直到匹配条件 |
| `bbcom_mirror_send_and_read_until` | 发送并读取直到匹配条件 |
| `bbcom_mirror_monitor` | 监控串口数据流 |
| `bbcom_serial_status` | 查询串口详细状态 |

## 验证安装

启动后可使用 `bbcom_version` 工具验证：

```
> bbcom_version
{
  "name": "bbcom-mcp",
  "version": "1.0.0"
}
```
