"""CLI for the same live RPC used by MCP (no copied protocol engine)."""
import argparse
import json
import sys
from pathlib import Path
from bbcom_mcp_server import _mirror_rpc, _rpc_result_to_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', nargs='?', default='automation_capabilities')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--args', default='{}', help='JSON object; prefer --args-file for paths/large templates')
    group.add_argument('--args-file', type=Path, help='UTF-8 JSON argument object')
    parser.add_argument('--timeout', type=float, default=35, help='Response timeout, not transfer timeout')
    options = parser.parse_args()
    try:
        if not 0 < options.timeout <= 120:
            raise ValueError('timeout must be in (0, 120]')
        args = json.loads(options.args_file.read_text(encoding='utf-8-sig') if options.args_file else options.args)
        if not isinstance(args, dict):
            raise ValueError('Arguments must be an object')
        result = json.loads(_rpc_result_to_json(_mirror_rpc(options.command, args, timeout_s=options.timeout)))
    except (ValueError, OSError) as error:
        result = {'type': 'error', 'message': str(error)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result.get('type') == 'error' else 0


if __name__ == '__main__':
    sys.exit(main())
