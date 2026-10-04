"""Hardware-test safety logic; all inverter responses here are simulated."""

from __future__ import annotations

import asyncio
from argparse import Namespace
from decimal import Decimal
import importlib.util
import json
from pathlib import Path
import struct
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / "tools" / "hardware_controls.py"
SPEC = importlib.util.spec_from_file_location("hardware_controls", SOURCE)
hardware = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = hardware
SPEC.loader.exec_module(hardware)


def control(**changes):
    options = dict(key="battery_float_voltage", register=0xE009, kind="scaled_u16",
                   step=Decimal("0.2"), scale=Decimal("0.2"), minimum=Decimal(20),
                   maximum=Decimal(33), choices=(), writable=True)
    options.update(changes)
    return hardware.Control(**options)


class MemoryJournal:
    def __init__(self):
        self.rows = []

    def record(self, event, **fields):
        self.rows.append({"event": event, **fields})


class Device:
    def __init__(self, journal, *, value=142, write_error=False, mismatch=False,
                 restore_fail=False, identity_error=False):
        self.value = value
        self.journal = journal
        self.writes = []
        self.write_error = write_error
        self.mismatch = mismatch
        self.restore_fail = restore_fail
        self.identity_error = identity_error

    async def identify(self, pn):
        if self.identity_error:
            raise ValueError("wrong unit")

    async def read(self, register):
        return [self.value]

    async def write(self, register, value):
        # Tests also prove the journal is recorded before the FIRST mutation.
        assert self.journal.rows[0]["event"] == "original_saved"
        self.writes.append((register, value))
        if len(self.writes) == 2 and self.restore_fail:
            raise ConnectionError("lost during restore")
        if len(self.writes) == 1 and self.mismatch:
            return
        self.value = value
        if len(self.writes) == 1 and self.write_error:
            raise TimeoutError("write applied, acknowledgement lost")


class PlanningTests(unittest.TestCase):
    def test_numeric_step_uses_pack_scale_and_prefers_decrease(self):
        self.assertEqual(control().candidate(142, (Decimal(28), Decimal(29))), 141)

    def test_numeric_requires_explicit_safe_window(self):
        for window in (None, (Decimal(28), Decimal(28)), (Decimal(10), Decimal(40))):
            with self.subTest(window=window), self.assertRaises(ValueError):
                control().candidate(142, window)

    def test_at_minimum_uses_one_upward_step_without_wrapping(self):
        self.assertEqual(control().candidate(100, (Decimal(20), Decimal("20.2"))), 101)

    def test_unrepresentable_step_is_rejected(self):
        with self.assertRaises(ValueError):
            control(step=Decimal("0.1")).candidate(142, (Decimal(28), Decimal(29)))

    def test_excluded_and_unknown_enums_are_not_writable(self):
        with self.assertRaises(ValueError):
            control(writable=False).candidate(142, (Decimal(28), Decimal(29)))
        enum = control(kind="enum", choices=(0, 1, 2))
        self.assertEqual(enum.candidate(2, None), 1)
        with self.assertRaises(ValueError):
            enum.candidate(9, None)

    def test_boolean_accepts_only_known_states(self):
        boolean = control(kind="bool")
        self.assertEqual(boolean.candidate(1, None), 0)
        with self.assertRaises(ValueError):
            boolean.candidate(2, None)

    def test_profile_cannot_introduce_password_or_power_write(self):
        profile = {"profile_key": "srne_modbus/smx_ii.json", "driver_key": "srne_modbus",
                   "capabilities": [
                       {"key": "alarm_enable", "register": 0xE203, "value_kind": "bool"},
                       {"key": "inverter_power", "register": 0xDF00, "value_kind": "bool"},
                       {"key": "alarm_enable_2", "register": 0xE210, "value_kind": "bool"},
                   ]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            path.write_text(json.dumps(profile), encoding="utf-8")
            self.assertTrue(all(not item.writable for item in hardware.load_controls(path)))

    def test_journal_is_durable_and_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.jsonl"
            journal = hardware.Journal(path)
            try:
                journal.record("original_saved", original=142)
                self.assertEqual(json.loads(path.read_text())["original"], 142)
                with self.assertRaises(FileExistsError):
                    hardware.Journal(path)
            finally:
                journal.close()

    def test_modbus_crc_slave_and_exception_validation(self):
        reply = hardware.rtu(bytes.fromhex("010302008E"))
        self.assertEqual(hardware.validate_reply(reply, 3), reply)
        for bad in (reply[:-1] + bytes((reply[-1] ^ 1,)),
                    hardware.rtu(bytes.fromhex("020302008E")),
                    hardware.rtu(bytes.fromhex("01830B"))):
            with self.assertRaises(ValueError):
                hardware.validate_reply(bad, 3)


class CapturedPnReplyTests(unittest.IsolatedAsyncioTestCase):
    # TCP payload captured from QA521322880760: TID 1, advertised device code
    # 0x0102/address 0xFF, FC2, status 0, parameter 2, exact collector PN.
    PN_FRAME = bytes.fromhex("000101020012ff0200025141353231333232383830373630")

    def wire_with_reply(self, frame):
        reader = asyncio.StreamReader()

        class Writer:
            def __init__(self):
                self.requests = []
                self.closed = False

            def write(self, data):
                self.requests.append(data)
                reader.feed_data(frame)

            async def drain(self):
                pass

            def close(self):
                self.closed = True

        writer = Writer()
        return hardware.Wire(reader, writer, 1), writer

    async def test_captured_stock_pn_reply_accepts_advertised_identity_header(self):
        wire, writer = self.wire_with_reply(self.PN_FRAME)
        reply = await wire.exchange(b"\x02", function=2, devcode=0, address=1)
        self.assertEqual(writer.requests, [bytes.fromhex("000100000003010202")])
        self.assertEqual(reply, b"\x00\x02QA521322880760")
        self.assertFalse(writer.closed)

    async def test_wrong_tid_or_function_in_pn_reply_still_closes_connection(self):
        for tid, fc in ((2, 2), (1, 4)):
            with self.subTest(tid=tid, fc=fc):
                frame = hardware.HEADER.pack(tid, 0x0102, 18, 255, fc) + self.PN_FRAME[8:]
                wire, writer = self.wire_with_reply(frame)
                with self.assertRaisesRegex(ValueError, "uncorrelated EyeBond reply"):
                    await wire.exchange(b"\x02", function=2, devcode=0, address=1)
                self.assertTrue(writer.closed)

    async def test_captured_reply_with_wrong_expected_pn_prevents_register_requests(self):
        wire, writer = self.wire_with_reply(self.PN_FRAME)
        with self.assertRaisesRegex(ValueError, "collector PN mismatch"):
            await wire.identify("OTHER-PN")
        self.assertEqual(len(writer.requests), 1)  # no forwarded reads or writes

    async def test_route_mismatch_is_still_rejected_for_forwarded_modbus(self):
        reply = hardware.rtu(bytes.fromhex("010302008E"))
        frame = hardware.HEADER.pack(1, 0x0102, len(reply) + 2, 255, 4) + reply
        wire, writer = self.wire_with_reply(frame)
        with self.assertRaisesRegex(ValueError, "uncorrelated EyeBond reply"):
            await wire.read(0xE009)
        self.assertTrue(writer.closed)

    async def test_other_collector_queries_do_not_relax_route_matching(self):
        wire, writer = self.wire_with_reply(self.PN_FRAME)
        with self.assertRaisesRegex(ValueError, "uncorrelated EyeBond reply"):
            await wire.exchange(b"\x06", function=2, devcode=0, address=1)
        self.assertTrue(writer.closed)


class RoundTripTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_changes_reads_and_restores_exact_raw_word(self):
        journal = MemoryJournal()
        device = Device(journal)
        await hardware.round_trip(device, control(), 142, 141, journal, "PN")
        self.assertEqual(device.writes, [(0xE009, 141), (0xE009, 142)])
        self.assertEqual(device.value, 142)
        self.assertEqual(journal.rows[-1]["event"], "PASS")

    async def test_lost_ack_after_mutation_still_restores_but_never_passes(self):
        journal = MemoryJournal()
        device = Device(journal, write_error=True)
        with self.assertRaises(TimeoutError):
            await hardware.round_trip(device, control(), 142, 141, journal, "PN")
        self.assertEqual(device.value, 142)
        self.assertEqual(journal.rows[-1]["event"], "original_restored")

    async def test_readback_mismatch_is_failure_even_if_original_unchanged(self):
        journal = MemoryJournal()
        device = Device(journal, mismatch=True)
        with self.assertRaises(ValueError):
            await hardware.round_trip(device, control(), 142, 141, journal, "PN")
        self.assertEqual(device.writes, [(0xE009, 141)])
        self.assertEqual(device.value, 142)

    async def test_restore_failure_retains_original_and_is_fatal(self):
        journal = MemoryJournal()
        device = Device(journal, restore_fail=True)
        with self.assertRaises(hardware.RestoreError):
            await hardware.round_trip(device, control(), 142, 141, journal, "PN")
        self.assertEqual(journal.rows[-1]["event"], "RESTORE_FAILED")
        self.assertEqual(journal.rows[-1]["original"], 142)
        self.assertFalse(any(row["event"] == "PASS" for row in journal.rows))

    async def test_clamped_or_external_third_value_is_not_blindly_overwritten(self):
        journal = MemoryJournal()
        device = Device(journal)

        async def changed(register, value):
            device.writes.append((register, value))
            device.value = 140

        device.write = changed
        with self.assertRaises(hardware.RestoreError):
            await hardware.round_trip(device, control(), 142, 141, journal, "PN")
        self.assertEqual(device.writes, [(0xE009, 141)])
        self.assertEqual(journal.rows[-1]["event"], "RESTORE_FAILED")

    async def test_journal_failure_before_write_prevents_any_mutation(self):
        class BrokenJournal(MemoryJournal):
            def record(self, event, **fields):
                raise OSError("disk full")

        journal = BrokenJournal()
        device = Device(journal)
        with self.assertRaises(OSError):
            await hardware.round_trip(device, control(), 142, 141, journal, "PN")
        self.assertEqual(device.writes, [])

    async def test_no_write_to_wrong_identity_or_concurrently_changed_setting(self):
        for options in ({"identity_error": True}, {"value": 143}):
            journal = MemoryJournal()
            device = Device(journal, **options)
            with self.assertRaises(ValueError):
                await hardware.round_trip(device, control(), 142, 141, journal, "PN")
            self.assertEqual(device.writes, [])

    async def test_cancellation_after_write_attempts_restore(self):
        journal = MemoryJournal()
        device = Device(journal)
        original_write = device.write

        async def cancel_after_write(register, value):
            await original_write(register, value)
            if len(device.writes) == 1:
                raise asyncio.CancelledError()

        device.write = cancel_after_write
        with self.assertRaises(asyncio.CancelledError):
            await hardware.round_trip(device, control(), 142, 141, journal, "PN")
        self.assertEqual(device.value, 142)
        self.assertEqual(journal.rows[-1]["event"], "original_restored")

    async def test_wrong_identity_on_real_wire_prevents_writes(self):
        reader = asyncio.StreamReader()

        class Writer:
            def __init__(self):
                self.requests = []

            def write(self, data):
                self.requests.append(data)
                tid, code, _, address, fc = hardware.HEADER.unpack(data[:8])
                body = b"\x00\x02PN" if fc == 2 else hardware.rtu(
                    b"\x01\x03\x28" + b"".join(struct.pack(">H", ord(c)) for c in "SR-2206260036-300918")
                )
                reader.feed_data(hardware.HEADER.pack(tid, code, len(body) + 2, address, fc) + body)

            async def drain(self):
                pass

            def close(self):
                pass

        writer = Writer()
        with self.assertRaises(ValueError):
            await hardware.Wire(reader, writer, 1).identify("PN")
        self.assertEqual(len(writer.requests), 2)
        self.assertEqual(writer.requests[-1][9], 3)  # only a Modbus READ

    async def test_full_round_trip_through_actual_bridge_with_simulated_inverter(self):
        from test_bridge import make_bridge, tcp_case

        bridge = make_bridge()
        journal = MemoryJournal()
        registers = {53 + index: ord(char) for index, char in enumerate(hardware.PRODUCT_INFO)}
        registers[0xE009] = 142
        writes = []

        async def serial_exchange(request):
            hardware.validate_reply(request, request[1])
            _, function, register, value = struct.unpack(">BBHH", request[:-2])
            if function == 3:
                return hardware.rtu(bytes((1, 3, value * 2)) + b"".join(
                    struct.pack(">H", registers[register + offset]) for offset in range(value)
                ))
            self.assertEqual(function, 6)
            registers[register] = value
            writes.append((register, value))
            return request

        bridge.serial_exchange = serial_exchange
        server, reader, writer = await tcp_case(bridge, b"")
        try:
            wire = hardware.Wire(reader, writer, 2)
            await hardware.round_trip(wire, control(), 142, 141, journal, "V0000000000000")
            self.assertEqual(writes, [(0xE009, 141), (0xE009, 142)])
            self.assertEqual(journal.rows[-1]["event"], "PASS")
        finally:
            writer.close()
            await writer.wait_closed()
            server.close()
            await server.wait_closed()


def wifi_args(report, **changes):
    options = dict(transport="wifi", listen="127.0.0.1", peer_ip="127.0.0.1",
                   pn="W00000000000000001", port=8898, return_host="127.0.0.1",
                   return_port=8899, timeout=1, connect_timeout=1,
                   report=str(report), write=True, control=["input_change_alarm"],
                   settle_seconds=0)
    options.update(changes)
    return Namespace(**options)


class WifiPlanningTests(unittest.TestCase):
    def test_delayed_udp_reply_is_received_before_discovery_socket_closes(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as collector:
            collector.bind(("127.0.0.1", 0))
            collector.settimeout(1)
            requests = []

            def reply():
                payload, peer = collector.recvfrom(2048)
                requests.append(payload)
                time.sleep(0.02)  # reproduces a real reply after sendto returns
                collector.sendto(b"rsp>server=1;", peer)

            worker = threading.Thread(target=reply)
            worker.start()
            try:
                response = hardware.redirect_wifi(
                    "127.0.0.1", "127.0.0.1", "127.0.0.1", 8898,
                    udp_port=collector.getsockname()[1])
            finally:
                worker.join(timeout=2)
            self.assertFalse(worker.is_alive())
            self.assertEqual(response, b"rsp>server=1;")
            self.assertEqual(requests, [b"set>server=127.0.0.1:8898;"])

    def test_return_endpoint_required_before_connecting(self):
        for changes in ({"return_host": None}, {"return_port": None},
                        {"return_port": 0}, {"return_host": "255.255.255.255"},
                        {"return_host": "224.0.0.1"}, {"return_port": 8898}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                hardware.validate_connection_options(wifi_args("unused", **changes))

    def test_redirect_is_targeted_and_matches_upstream_variants(self):
        with patch.object(hardware.socket, "socket") as factory:
            sock = factory.return_value.__enter__.return_value
            sock.recvfrom.side_effect = [socket.timeout(), socket.timeout(),
                                        (b"rsp>server=2;", ("192.0.2.20", 58899))]
            hardware.redirect_wifi("192.0.2.10", "192.0.2.20", "192.0.2.30", 8899)
        sock = factory.return_value.__enter__.return_value
        sock.bind.assert_called_once_with(("192.0.2.10", 0))
        self.assertEqual([call.args for call in sock.sendto.call_args_list], [
            (b"set>server=192.0.2.30:8899;" + suffix, ("192.0.2.20", 58899))
            for suffix in (b"", b"\r\n", b"\n")
        ])
        sock.setsockopt.assert_not_called()  # never enable broadcast

    def test_udp_replies_from_wrong_peer_or_with_unknown_status_are_ignored(self):
        with patch.object(hardware.socket, "socket") as factory:
            sock = factory.return_value.__enter__.return_value
            sock.recvfrom.side_effect = [
                (b"rsp>server=2;", ("192.0.2.21", 58899)),
                (b"rsp>server=2;", ("192.0.2.20", 1234)),
                (b"rsp>server=9;", ("192.0.2.20", 58899)),
                (b"rsp>server=2;", ("192.0.2.20", 58899)),
            ]
            reply = hardware.redirect_wifi("192.0.2.10", "192.0.2.20", "192.0.2.30", 8899)
        self.assertEqual(reply, b"rsp>server=2;")
        self.assertEqual(sock.sendto.call_count, 1)

    def test_udp_silence_is_bounded_and_not_reported_as_an_acknowledgement(self):
        with patch.object(hardware.socket, "socket") as factory:
            sock = factory.return_value.__enter__.return_value
            sock.recvfrom.side_effect = socket.timeout()
            reply = hardware.redirect_wifi("192.0.2.10", "192.0.2.20", "192.0.2.30", 8899)
        self.assertIsNone(reply)
        self.assertEqual(sock.sendto.call_count, 3)
        self.assertEqual(sock.recvfrom.call_count, 3)


class SimulatedWifiCollector(asyncio.DatagramProtocol):
    """Stock-style reverse TCP peer, not USB Bridge; all registers simulated."""

    def __init__(self, *, pn="W00000000000000001", identity=hardware.PRODUCT_INFO,
                 mismatch=False, lost_ack=False, restore_fail=False, stock_identity_header=False):
        self.pn = pn
        self.registers = {53 + index: ord(char) for index, char in enumerate(identity)}
        self.registers[0xE211] = 1
        self.writes = []
        self.frames = []
        self.redirects = []
        self.task = None
        self.error = None
        self.mismatch = mismatch
        self.lost_ack = lost_ack
        self.restore_fail = restore_fail
        self.stock_identity_header = stock_identity_header

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, address):
        self.redirects.append(data)
        self.transport.sendto(b"rsp>server=2;", address)
        if self.task is None:
            endpoint = data.decode("ascii").strip().removeprefix("set>server=").removesuffix(";")
            host, port = endpoint.split(":")
            self.task = asyncio.create_task(self.callback(host, int(port)))

    async def callback(self, host, port):
        writer = None
        try:
            reader, writer = await asyncio.open_connection(host, port)
            # Heartbeat uses a short/truncated identity; FC2 provides full PN.
            body = self.pn[:14].encode("ascii")
            writer.write(hardware.HEADER.pack(0x8001, 0, len(body) + 2, 1, 1) + body)
            await writer.drain()
            while True:
                header = await reader.readexactly(8)
                tid, code, length, addr, fc = hardware.HEADER.unpack(header)
                request = await reader.readexactly(length - 2)
                self.frames.append((code, addr, fc, request))
                if fc == 2:
                    assert (code, addr, request) == (0, 1, b"\x02")
                    body = b"\x00\x02" + self.pn.encode("ascii") + b"\x00\x00"
                    if self.stock_identity_header:
                        code, addr = 0x0102, 255
                else:
                    assert (code, addr, fc) == (1, 255, 4)
                    hardware.validate_reply(request, request[1])
                    _, function, register, value = struct.unpack(">BBHH", request[:-2])
                    if function == 3:
                        body = hardware.rtu(bytes((1, 3, value * 2)) + b"".join(
                            struct.pack(">H", self.registers[register + offset])
                            for offset in range(value)
                        ))
                    else:
                        assert function == 6
                        self.writes.append((register, value))
                        if self.restore_fail and len(self.writes) == 2:
                            body = hardware.rtu(b"\x01\x86\x04")
                            writer.write(hardware.HEADER.pack(tid, code, len(body) + 2, addr, fc) + body)
                            await writer.drain()
                            continue
                        if not self.mismatch:
                            self.registers[register] = value
                        if self.lost_ack and len(self.writes) == 1:
                            break  # applied, but connection lost before ACK
                        body = request
                writer.write(hardware.HEADER.pack(tid, code, len(body) + 2, addr, fc) + body)
                await writer.drain()
        except asyncio.IncompleteReadError:
            pass
        except Exception as exc:
            self.error = exc
        finally:
            if writer is not None:
                writer.close()
                await writer.wait_closed()


class WifiRunTests(unittest.IsolatedAsyncioTestCase):
    async def simulate(self, **changes):
        fake_options = {key: changes.pop(key) for key in (
            "pn", "identity", "mismatch", "lost_ack", "restore_fail", "stock_identity_header")
                        if key in changes}
        collector = SimulatedWifiCollector(**fake_options)
        udp, _ = await asyncio.get_running_loop().create_datagram_endpoint(
            lambda: collector, local_addr=("127.0.0.1", 0))
        udp_port = udp.get_extra_info("sockname")[1]
        real_redirect = hardware.redirect_wifi

        def redirect(bind_ip, collector_ip, host, port):
            return real_redirect(bind_ip, collector_ip, host, port, udp_port=udp_port)

        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        try:
            with tempfile.TemporaryDirectory() as directory:
                args = wifi_args(Path(directory) / "report.jsonl", port=port, **changes)
                alarm = control(key="input_change_alarm", register=0xE211,
                                kind="bool", scale=Decimal(1))
                with patch.object(hardware, "redirect_wifi", side_effect=redirect), \
                     patch("builtins.input", return_value="input_change_alarm"):
                    try:
                        outcome = await hardware.run(args, (alarm,), {})
                    except Exception as exc:
                        outcome = exc
                # Let the local UDP return datagrams be received before cleanup.
                await asyncio.sleep(0.02)
                if collector.task is not None:
                    await asyncio.wait_for(collector.task, 2)
                rows = [json.loads(line) for line in Path(args.report).read_text().splitlines()]
                self.assertIsNone(collector.error)
                self.assertEqual(collector.redirects[-1], b"set>server=127.0.0.1:8899;")
                self.assertEqual(len(collector.redirects), 2)
                self.assertEqual(rows[0]["event"], "callback_original_saved")
                self.assertEqual(rows[-1]["event"], "callback_return_sent")
                self.assertFalse(rows[-1]["verified"])
                self.assertEqual(rows[-1]["udp_reply"], "rsp>server=2;")
                return outcome, collector, rows
        finally:
            udp.close()

    async def test_wifi_round_trip_over_real_tcp_and_udp_restores_original(self):
        result, collector, rows = await self.simulate()
        self.assertEqual(result, 0)
        self.assertEqual(collector.writes, [(0xE211, 0), (0xE211, 1)])
        self.assertEqual(collector.registers[0xE211], 1)
        self.assertTrue(any(row["event"] == "PASS" for row in rows))
        self.assertTrue(all(fc in (2, 4) for _, _, fc, _ in collector.frames))

    async def test_stock_pn_header_allows_round_trip_and_exact_restoration(self):
        result, collector, rows = await self.simulate(stock_identity_header=True)
        self.assertEqual(result, 0)
        self.assertEqual(collector.writes, [(0xE211, 0), (0xE211, 1)])
        self.assertEqual(collector.registers[0xE211], 1)
        self.assertTrue(any(row["event"] == "PASS" for row in rows))

    async def test_stock_pn_header_does_not_allow_a_different_inverter(self):
        result, collector, _ = await self.simulate(
            stock_identity_header=True, identity="SR-2206260036-300918")
        self.assertIsInstance(result, ValueError)
        self.assertEqual(collector.writes, [])

    async def test_wifi_read_only_does_not_write(self):
        result, collector, rows = await self.simulate(write=False, control=[])
        self.assertEqual(result, 0)
        self.assertEqual(collector.writes, [])
        self.assertTrue(any(row["event"] == "READ" for row in rows))
        self.assertFalse(any(row["event"] == "PASS" for row in rows))

    async def test_wrong_stock_pn_prevents_modbus_reads_and_writes(self):
        result, collector, _ = await self.simulate(pn="OTHER-PN")
        self.assertIsInstance(result, ValueError)
        self.assertEqual(collector.writes, [])
        self.assertEqual(len(collector.frames), 1)

    async def test_other_inverter_prevents_all_writes_and_returns_callback(self):
        result, collector, _ = await self.simulate(identity="SR-2206260036-300918")
        self.assertIsInstance(result, ValueError)
        self.assertEqual(collector.writes, [])

    async def test_wifi_readback_mismatch_never_passes(self):
        result, collector, rows = await self.simulate(mismatch=True)
        self.assertEqual(result, 1)
        self.assertEqual(collector.registers[0xE211], 1)
        self.assertFalse(any(row["event"] == "PASS" for row in rows))

    async def test_lost_wifi_connection_after_write_is_fatal_not_false_restore(self):
        result, collector, rows = await self.simulate(lost_ack=True)
        self.assertIsInstance(result, hardware.RestoreError)
        self.assertEqual(collector.registers[0xE211], 0)
        self.assertTrue(any(row["event"] == "RESTORE_FAILED" for row in rows))
        self.assertFalse(any(row["event"] == "PASS" for row in rows))
        saved = next(row for row in rows if row["event"] == "original_saved")
        self.assertEqual(saved["original"], 1)

    async def test_wifi_restore_rejection_is_fatal_and_returns_callback(self):
        result, collector, rows = await self.simulate(restore_fail=True)
        self.assertIsInstance(result, hardware.RestoreError)
        self.assertEqual(collector.registers[0xE211], 0)
        self.assertTrue(any(row["event"] == "RESTORE_FAILED" for row in rows))
        self.assertFalse(any(row["event"] == "PASS" for row in rows))

    async def test_connection_timeout_still_requests_original_callback(self):
        with tempfile.TemporaryDirectory() as directory:
            args = wifi_args(Path(directory) / "report.jsonl", port=0,
                             connect_timeout=0.01, write=False, control=[])
            with patch.object(hardware, "redirect_wifi", return_value=None) as redirect:
                with self.assertRaises(TimeoutError):
                    await hardware.run(args, (), {})
            self.assertEqual(redirect.call_count, 2)
            self.assertEqual(redirect.call_args.args[-2:], ("127.0.0.1", 8899))

    async def test_failed_initial_redirect_still_attempts_return(self):
        with tempfile.TemporaryDirectory() as directory:
            args = wifi_args(Path(directory) / "report.jsonl", port=0,
                             write=False, control=[])
            with patch.object(hardware, "redirect_wifi", side_effect=[OSError("UDP failure"), None]) as redirect:
                with self.assertRaises(OSError):
                    await hardware.run(args, (), {})
            self.assertEqual(redirect.call_count, 2)
            self.assertEqual(redirect.call_args.args[-2:], ("127.0.0.1", 8899))

    async def test_failed_callback_return_is_reported_as_fatal(self):
        with tempfile.TemporaryDirectory() as directory:
            args = wifi_args(Path(directory) / "report.jsonl", port=0,
                             connect_timeout=0.01, write=False, control=[])
            with patch.object(hardware, "redirect_wifi", side_effect=[None, OSError("UDP failure")]):
                with self.assertRaisesRegex(RuntimeError, "Callback return failed"):
                    await hardware.run(args, (), {})
            rows = [json.loads(line) for line in Path(args.report).read_text().splitlines()]
            self.assertEqual(rows[-1]["event"], "CALLBACK_RETURN_FAILED")


if __name__ == "__main__":
    unittest.main()
