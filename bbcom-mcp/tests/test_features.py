import asyncio
import json
import unittest
import socket
import threading
import sys
from pathlib import Path
from unittest.mock import patch
from mcp.server.fastmcp import FastMCP
import bbcom_features
import bbcom_mcp_server as server


class Registry:
    def __init__(self): self.tools = {}
    def tool(self):
        def add(fn): self.tools[fn.__name__] = fn; return fn
        return add


class FeaturesTest(unittest.TestCase):
    def setUp(self):
        self.registry = Registry()
        self.calls = []
        self.response = {'type': 'rpc', 'rpc': {'ok': True, 'result': {'active': False, 'state': 'completed'}}}
        def rpc(command, args, timeout_s):
            self.calls.append((command, args, timeout_s))
            return self.response
        bbcom_features.register(self.registry, rpc, server._rpc_result_to_json)

    def test_real_mcp_discovers_typed_tools(self):
        tools = asyncio.run(server.mcp.list_tools())
        names = {t.name for t in tools}
        self.assertTrue(self.registry.tools.keys() <= names)
        start = next(t for t in tools if t.name == 'bbcom_protocol_start')
        self.assertEqual(set(start.inputSchema['required']), {'direction', 'path', 'template'})

    def test_start_maps_fields_and_does_not_wait_or_launch_cli(self):
        self.registry.tools['bbcom_protocol_start']('receive', r'D:\new.bin', {'id': 'test'}, 129)
        self.assertEqual(self.calls, [('protocol_start', {'direction': 'receive', 'path': r'D:\new.bin', 'template': {'id': 'test'}, 'exactLength': 129}, 35)])

    def test_errors_propagate_and_cancel_is_session_specific(self):
        self.response = {'type': 'rpc', 'rpc': {'ok': False, 'error': 'Session is no longer current'}}
        result = json.loads(self.registry.tools['bbcom_protocol_wait']('old', .1))
        self.assertEqual(result['type'], 'error')
        self.registry.tools['bbcom_protocol_cancel']('old')
        self.assertEqual(self.calls[-1][1], {'sessionId': 'old'})

    def test_wait_timeout_never_cancels(self):
        self.response['rpc']['result']['active'] = True
        result = json.loads(self.registry.tools['bbcom_protocol_wait']('s', .01))
        self.assertTrue(result['waitTimedOut'])
        self.assertTrue(result['result']['active'])
        self.assertTrue(all(c[0] == 'protocol_status' for c in self.calls))

    def test_notes_clear_is_not_save_and_recording_stop_is_explicit(self):
        self.registry.tools['bbcom_notes']('clear')
        self.assertEqual(self.calls[-1][0], 'notes_clear')
        self.registry.tools['bbcom_log_recording']('stop', save_notes=False)
        self.assertEqual(self.calls[-1][1], {'action': 'stop', 'saveNotes': False})

    def test_floating_and_proxy_mapping(self):
        self.registry.tools['bbcom_timer']('control', {'action': 'reset'})
        self.assertEqual(self.calls[-1][:2], ('timer_control', {'action': 'reset'}))
        self.registry.tools['bbcom_proxy']('start', {'virtualPort': 'COM8', 'baudRate': 115200})
        self.assertEqual(self.calls[-1][0], 'proxy_start')

    def test_oversized_rpc_is_rejected_before_connecting(self):
        with patch.object(server, '_get_mirror_connection', return_value=('127.0.0.1', 5000)), patch.object(server.socket, 'create_connection') as connection:
            result = server._mirror_rpc('protocol_validate_template', {'content': 'x' * 131072})
        self.assertEqual(result['type'], 'error')
        connection.assert_not_called()

    def test_socket_response_fragmentation_noise_and_request_identity(self):
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0)); listener.listen(1)
        address = listener.getsockname()
        errors = []
        def peer():
            try:
                with listener, listener.accept()[0] as connection:
                    request = b''
                    while not request.endswith(b'\n'):
                        request += connection.recv(1024)
                    parsed = json.loads(request[5:])
                    connection.sendall(b'device log\n\x01RPCRESP {"id":"wrong","ok":true}\n')
                    response = b'\x01RPCRESP ' + json.dumps({'id': parsed['id'], 'ok': True, 'result': {'received': len(parsed['args']['content'])}}).encode() + b'\n'
                    for byte in response:
                        connection.sendall(bytes([byte]))
            except Exception as e: errors.append(e)
        worker = threading.Thread(target=peer, daemon=True); worker.start()
        with patch.object(server, '_get_mirror_connection', return_value=address):
            result = server._mirror_rpc('protocol_validate_template', {'content': 'a' * 5000}, timeout_s=3)
        worker.join(timeout=3)
        self.assertFalse(errors)
        self.assertEqual(result['rpc']['result']['received'], 5000)

    def test_stdio_server_lists_and_calls_new_tools(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        async def check():
            params = StdioServerParameters(command=sys.executable, args=[str(Path(server.__file__).resolve())])
            async with stdio_client(params) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    self.assertIn('bbcom_waveform', {tool.name for tool in listed.tools})
                    result = await session.call_tool('bbcom_protocol_wait', {'session_id': '', 'timeout_seconds': 0})
                    payload = json.loads(result.content[0].text)
                    self.assertEqual(payload['type'], 'error')
        asyncio.run(check())


if __name__ == '__main__': unittest.main()
