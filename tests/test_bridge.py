"""Behavior tests for framing, connection management and serial forwarding."""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
from pathlib import Path
import sys
import os
import tempfile
import types
import unittest


try:
    import serial  # noqa: F401
except ImportError:
    serial_stub = types.ModuleType("serial")
    serial_stub.EIGHTBITS = 8
    serial_stub.PARITY_NONE = "N"
    serial_stub.STOPBITS_ONE = 1
    sys.modules["serial"] = serial_stub

SOURCE = Path(os.environ.get(
    "BRIDGE_SOURCE",
    Path(__file__).resolve().parents[1] / "isolar_eybond_usb_bridge" / "bridge.py",
))
SPEC = importlib.util.spec_from_file_location("eybond_bridge", SOURCE)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def make_bridge(**overrides):
    options = dict(
        pn="V0000000000000", baud=9600, heartbeat_interval=60,
        ha_host="127.0.0.1", ha_port=8899, serial_device="unused",
        udp_port=58899, version="test", allow_remote_redirect=False,
    )
    options.update(overrides)
    return module.Bridge(argparse.Namespace(**options))


async def tcp_case(bridge, payload):
    async def server(reader, writer):
        try:
            return await bridge.handle_connection(reader, writer)
        finally:
            writer.close()

    listener = await asyncio.start_server(server, "127.0.0.1", 0)
    port = listener.sockets[0].getsockname()[1]
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    await reader.readexactly(22)  # unsolicited heartbeat
    writer.write(payload)
    await writer.drain()
    return listener, reader, writer


class StreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_binary_tid_starting_with_A_and_coalesced_at_query(self):
        bridge = make_bridge()
        binary = module.build_frame(0x4101, 0, 1, module.FC_QUERY, b"\x06")
        server, reader, writer = await tcp_case(bridge, binary + b"AT+UART?\r\n")
        try:
            header = await reader.readexactly(8)
            tid, _, wire_len, _, code = module.HEADER.unpack(header)
            answer = await reader.readexactly(wire_len - 2)
            self.assertEqual((0x4101, module.FC_QUERY), (tid, code))
            self.assertIn(b"esp-collector/", answer)
            expected = b"AT+UART:9600,8,1,NONE\r\n"
            self.assertEqual(expected, await reader.readexactly(len(expected)))
        finally:
            writer.close()
            server.close()
            await server.wait_closed()

    async def test_invalid_frame_drops_connection_without_crashing(self):
        bridge = make_bridge()
        server, reader, writer = await tcp_case(
            bridge, b"\x00\x01\x00\x00\xff\xff\x01\x02"
        )
        try:
            self.assertEqual(b"", await asyncio.wait_for(reader.read(), 1))
        finally:
            writer.close()
            server.close()
            await server.wait_closed()

    async def test_forward_preserves_tid_and_raw_reply(self):
        bridge = make_bridge()

        async def fake_serial(request):
            self.assertEqual(b"\x05\x03\x13\x8c", request)
            return b"\x05\x03\x02\x00\x01\x89\x84"

        bridge.serial_exchange = fake_serial
        request = module.build_frame(123, 4, 5, module.FC_FORWARD, b"\x05\x03\x13\x8c")
        server, reader, writer = await tcp_case(bridge, request)
        try:
            header = await reader.readexactly(8)
            tid, devcode, wire_len, addr, code = module.HEADER.unpack(header)
            self.assertEqual((123, 4, 5, 4), (tid, devcode, addr, code))
            self.assertEqual(b"\x05\x03\x02\x00\x01\x89\x84",
                             await reader.readexactly(wire_len - 2))
        finally:
            writer.close()
            server.close()
            await server.wait_closed()

    async def test_stop_closes_idle_connection(self):
        bridge = make_bridge()
        server, reader, writer = await tcp_case(bridge, b"")
        try:
            bridge.request_stop()
            self.assertEqual(b"", await asyncio.wait_for(reader.read(), 1))
        finally:
            writer.close()
            server.close()
            await server.wait_closed()

    async def test_serial_silence_produces_no_response(self):
        bridge = make_bridge()

        async def no_reply(_request):
            return b""

        bridge.serial_exchange = no_reply
        request = module.build_frame(123, 0, 1, 4, b"\x05\x03")
        server, reader, writer = await tcp_case(bridge, request)
        try:
            with self.assertRaises(asyncio.TimeoutError):
                await asyncio.wait_for(reader.readexactly(1), 0.05)
        finally:
            writer.close()
            server.close()
            await server.wait_closed()


class IdentityAndSecurityTests(unittest.TestCase):
    def test_pn_persists_and_explicit_pn_wins(self):
        with tempfile.TemporaryDirectory() as folder:
            first = module.collector_identity("", folder)
            self.assertRegex(first, r"^V[0-9]{13}$")
            self.assertEqual(first, module.collector_identity("", folder))
            self.assertEqual("V1234567890123",
                             module.collector_identity("V1234567890123", folder))

    def test_discovery_cannot_redirect_configured_endpoint(self):
        bridge = make_bridge()
        protocol = module.DiscoveryProtocol(bridge)
        replies = []
        protocol.transport = types.SimpleNamespace(
            sendto=lambda data, peer: replies.append((data, peer))
        )
        protocol.datagram_received(
            b"set>server=10.0.0.99:8899;", ("10.0.0.99", 12000)
        )
        self.assertEqual([], replies)
        self.assertEqual(("127.0.0.1", 8899), bridge.endpoint)
        protocol.datagram_received(
            b"set>server=127.0.0.1:8899;", ("127.0.0.1", 12000)
        )
        self.assertEqual(1, len(replies))

    def test_at_write_requires_real_effect(self):
        bridge = make_bridge()
        self.assertIsNone(bridge.at_reply(b"AT+SOMETHING=1\r\n"))
        self.assertEqual(b"AT+UART:W000\r\n",
                         bridge.at_reply(b"AT+UART=19200,8,1,NONE\r\n"))
        self.assertEqual(19200, bridge.baud)


if __name__ == "__main__":
    unittest.main()
