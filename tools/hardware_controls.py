#!/usr/bin/env python3
"""Supervised SMX-II setting round trips through USB Bridge or EyeBond Wi-Fi.

Not part of CI: real writes require --write, selected controls and confirmation.
The inverter profile is supplied from EyeBond Local, never bundled into Bridge.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import ipaddress
import json
import math
import os
from pathlib import Path
import socket
import struct
from time import monotonic


HEADER = struct.Struct(">HHHBB")
PRODUCT_INFO = "SR-2206260036-300917"
# These are not safe incremental/reversible tests, even if represented as bools.
EXCLUDED = {
    "inverter_power", "battery_equalize_now", "battery_equalization_enable",
    "battery_type", "output_frequency_setting", "power_saving_mode",
    "restart_on_overload", "restart_on_overtemperature", "bypass_on_overload",
}
# An independently reviewed register allowlist. A future/mutated profile must
# not silently turn password, action or topology registers into test targets.
WRITE_REGISTERS = {
    "output_priority": 0xE204, "charger_source_priority": 0xE20F,
    "ac_input_voltage_range": 0xE20B, "output_voltage_setting": 0xE208,
    "max_charge_current": 0xE20A, "max_ac_charge_current": 0xE205,
    "max_pv_charge_current": 0xE001, "battery_capacity": 0xE002,
    "battery_overcharge_voltage": 0xE005, "battery_charge_voltage_limit": 0xE006,
    "battery_equalization_voltage": 0xE007, "battery_boost_voltage": 0xE008,
    "battery_float_voltage": 0xE009, "battery_charge_recovery_voltage": 0xE00A,
    "battery_undervoltage_recovery": 0xE00B, "battery_undervoltage_alarm": 0xE00C,
    "battery_overdischarge_voltage": 0xE00D, "battery_discharge_limit_voltage": 0xE00E,
    "battery_overdischarge_delay": 0xE010, "battery_equalization_time": 0xE011,
    "battery_boost_time": 0xE012, "battery_equalization_interval": 0xE013,
    "battery_equalization_timeout": 0xE023, "turn_to_utility_voltage": 0xE01B,
    "turn_to_inverter_voltage": 0xE022, "alarm_enable": 0xE210,
    "input_change_alarm": 0xE211,
}


def crc16(data: bytes) -> int:
    value = 0xFFFF
    for byte in data:
        value ^= byte
        for _ in range(8):
            value = (value >> 1) ^ (0xA001 if value & 1 else 0)
    return value


def rtu(data: bytes) -> bytes:
    return data + crc16(data).to_bytes(2, "little")


def validate_reply(reply: bytes, function: int) -> bytes:
    if len(reply) < 5 or crc16(reply[:-2]) != int.from_bytes(reply[-2:], "little"):
        raise ValueError("invalid Modbus response length/CRC")
    if reply[0] != 1:
        raise ValueError("unexpected Modbus slave")
    if reply[1] == (function | 0x80):
        if len(reply) != 5:
            raise ValueError("invalid exception response")
        raise ValueError(f"Modbus exception {reply[2]}; no password/login writes are attempted")
    if reply[1] != function:
        raise ValueError("unexpected Modbus function")
    return reply


@dataclass(frozen=True)
class Control:
    key: str
    register: int
    kind: str
    step: Decimal
    scale: Decimal
    minimum: Decimal
    maximum: Decimal
    choices: tuple[int, ...]
    writable: bool

    def value(self, word: int) -> Decimal:
        return Decimal(word) * self.scale

    def candidate(self, original: int, window: tuple[Decimal, Decimal] | None) -> int:
        if not self.writable:
            raise ValueError("excluded: hazardous, masked, multiword or unsupported command")
        if self.kind == "enum":
            if original not in self.choices or len(self.choices) < 2:
                raise ValueError("original is not a known enum value")
            index = self.choices.index(original)
            return self.choices[index - 1 if index else 1]
        if self.kind == "bool":
            if original not in (0, 1):
                raise ValueError("original is not a known boolean value")
            return 1 - original
        if window is None:
            raise ValueError("numeric setting requires an owner-approved --window")
        low, high = window
        current = self.value(original)
        if not (self.minimum <= low <= current <= high <= self.maximum):
            raise ValueError("original/window outside profile bounds")
        wire_step = self.step / self.scale
        if wire_step <= 0 or wire_step != wire_step.to_integral_value():
            raise ValueError("profile step cannot be represented exactly on the wire")
        # Prefer decreasing the setting; never wrap around at either limit.
        for word in (original - int(wire_step), original + int(wire_step)):
            if 0 <= word <= 65535 and low <= self.value(word) <= high:
                return word
        raise ValueError("approved window does not allow a one-step change")


def load_controls(path: Path) -> tuple[Control, ...]:
    profile = json.loads(path.read_text(encoding="utf-8"))
    if (profile.get("profile_key"), profile.get("driver_key")) != (
        "srne_modbus/smx_ii.json", "srne_modbus",
    ):
        raise ValueError("requires the separate identity-gated SMX-II profile")
    defaults = profile.get("capability_defaults", {})
    result = []
    for entry in profile["capabilities"]:
        item = {**defaults, **entry}
        scale = (
            Decimal(1) / Decimal(str(item["divisor"])) if item.get("divisor")
            else Decimal(str(item.get("multiplier", 1)))
        )
        key, register, kind = item["key"], int(item["register"]), item["value_kind"]
        if not scale.is_finite() or scale <= 0:
            raise ValueError("invalid profile scale")
        result.append(Control(
            key, register, kind, Decimal(str(item.get("step", 1))), scale,
            Decimal(str(item.get("minimum", 0))),
            Decimal(str(item.get("maximum", 65535))),
            tuple(int(choice["value"]) for choice in sorted(
                item.get("choices", []), key=lambda choice: choice.get("order", 0),
            )),
            key not in EXCLUDED and WRITE_REGISTERS.get(key) == register
            and kind in {"u16", "scaled_u16", "enum", "bool"}
            and not item.get("bitmask") and item.get("word_count", 1) == 1
            and item.get("write_function", 6) == 6,
        ))
    if len({item.key for item in result}) != len(result):
        raise ValueError("duplicate control keys")
    return tuple(result)


class Journal:
    def __init__(self, path: Path):
        self.stream = path.open("x", encoding="utf-8")

    def record(self, event: str, **fields):
        row = {"time": datetime.now(timezone.utc).isoformat(), "event": event, **fields}
        self.stream.write(json.dumps(row, ensure_ascii=True) + "\n")
        self.stream.flush()
        os.fsync(self.stream.fileno())

    def close(self):
        self.stream.close()


class Wire:
    def __init__(self, reader, writer, timeout: float):
        self.reader, self.writer, self.timeout = reader, writer, timeout
        self.tid = 0

    async def exchange(self, payload: bytes, *, function=4, devcode=1, address=255):
        self.tid += 1
        if self.tid >= 0x8000:
            raise ValueError("transaction limit reached")
        self.writer.write(HEADER.pack(self.tid, devcode, len(payload) + 2, address, function) + payload)
        await self.writer.drain()
        try:
            async with asyncio.timeout(self.timeout):
                while True:
                    header = await self.reader.readexactly(8)
                    tid, code, length, addr, fc = HEADER.unpack(header)
                    if not 2 <= length <= 514:
                        raise ValueError("invalid EyeBond frame length")
                    body = await self.reader.readexactly(length - 2)
                    if fc == 1:  # unsolicited collector heartbeat, not a reply
                        continue
                    if (tid, code, addr, fc) != (self.tid, devcode, address, function):
                        raise ValueError("uncorrelated EyeBond reply")
                    return body
        except BaseException:
            # A partial/late frame must not be reused to confirm another command.
            self.writer.close()
            raise

    async def read(self, register: int, count=1) -> list[int]:
        request = rtu(struct.pack(">BBHH", 1, 3, register, count))
        reply = validate_reply(await self.exchange(request), 3)
        if len(reply) != 5 + 2 * count or reply[2] != 2 * count:
            raise ValueError("unexpected register count")
        return list(struct.unpack(f">{count}H", reply[3:-2]))

    async def write(self, register: int, value: int):
        request = rtu(struct.pack(">BBHH", 1, 6, register, value))
        reply = validate_reply(await self.exchange(request), 6)
        if reply != request:
            raise ValueError("write acknowledgement does not match exact register/value")

    async def identify(self, pn: str):
        reply = await self.exchange(b"\x02", function=2, devcode=0, address=1)
        if reply[:2] != b"\x00\x02" or reply[2:].rstrip(b"\x00").decode("ascii") != pn:
            raise ValueError("collector PN mismatch")
        words = await self.read(53, 20)
        identity = "".join(chr(word & 255) for word in words).strip("\x00 ")
        if identity != PRODUCT_INFO:
            raise ValueError(f"unverified inverter identity: {identity!r}; no writes allowed")


class RestoreError(RuntimeError):
    pass


async def round_trip(wire, control: Control, original: int, candidate: int, journal, pn: str,
                     *, settle_seconds: float = 0):
    """Journal BEFORE mutation; always verify restoration, even after write error."""
    await wire.identify(pn)
    if await wire.read(control.register) != [original]:
        raise ValueError("setting changed since confirmation; aborting without write")
    journal.record("original_saved", key=control.key, register=control.register,
                   original=original, candidate=candidate, pn=pn, identity=PRODUCT_INFO)
    error = None
    try:
        await wire.write(control.register, candidate)
        journal.record("write_ack", key=control.key)
        await asyncio.sleep(settle_seconds)
        if await wire.read(control.register) != [candidate]:
            raise ValueError("candidate readback mismatch")
        journal.record("candidate_verified", key=control.key, raw=candidate)
    except BaseException as exc:
        error = exc
        journal.record("test_failed", key=control.key, error=type(exc).__name__ + ": " + str(exc))
    finally:
        try:
            await wire.identify(pn)
            current = (await wire.read(control.register))[0]
            if current != original:
                if current != candidate:
                    raise ValueError("unexpected third value; refusing to overwrite possible external change")
                await wire.write(control.register, original)
            await asyncio.sleep(settle_seconds)
            if await wire.read(control.register) != [original]:
                raise ValueError("original readback mismatch")
            await asyncio.sleep(settle_seconds)
            if await wire.read(control.register) != [original]:
                raise ValueError("original did not remain restored")
            journal.record("original_restored", key=control.key, raw=original)
        except BaseException as exc:
            journal.record("RESTORE_FAILED", key=control.key, register=control.register,
                           original=original, error=type(exc).__name__ + ": " + str(exc))
            raise RestoreError("RESTORE FAILED: stop testing and check inverter/journal manually") from exc
    if error is not None:
        raise error
    journal.record("PASS", key=control.key)


def parse_windows(items: list[str]) -> dict[str, tuple[Decimal, Decimal]]:
    result = {}
    for item in items:
        key, low, high = item.split(":")
        values = Decimal(low), Decimal(high)
        if key in result or not all(value.is_finite() for value in values) or values[0] > values[1]:
            raise ValueError("invalid or duplicate --window")
        result[key] = values
    return result


def validate_connection_options(args):
    addresses = [args.listen, args.peer_ip]
    if args.transport == "wifi":
        if not args.return_host or args.return_port is None:
            raise ValueError("--transport wifi requires the original --return-host and --return-port")
        addresses.append(args.return_host)
        if not 1 <= args.return_port <= 65535:
            raise ValueError("invalid --return-port")
        if (args.return_host, args.return_port) == (args.listen, args.port):
            raise ValueError("return endpoint must differ from the test listener")
    elif args.return_host is not None or args.return_port is not None:
        raise ValueError("return endpoint options are only used with --transport wifi")
    for address in addresses:
        ip = ipaddress.IPv4Address(address)
        if ip.is_unspecified or ip.is_multicast or int(ip) == 0xFFFFFFFF:
            raise ValueError("use specific unicast IPv4 addresses")


def redirect_wifi(bind_ip: str, collector_ip: str, server_ip: str, server_port: int,
                  *, udp_port: int = 58899, timeout: float = 1):
    """Targeted discovery variants from EyeBond Local collector/discovery.py.

    A UDP reply is not proof of TCP endpoint restoration. No broadcast,
    persistent FC3/AT endpoint writes, reset, baud changes or login are attempted.
    """
    base = f"set>server={server_ip}:{server_port};".encode("ascii")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind((bind_ip, 0))
        for suffix in (b"", b"\r\n", b"\n"):
            sock.sendto(base + suffix, (collector_ip, udp_port))
            # Keep the source port open for the collector's reply. Closing right
            # after sendto makes the host return ICMP port-unreachable instead.
            # Try the next format only if this one receives no valid reply.
            deadline = monotonic() + timeout
            while True:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    break
                sock.settimeout(remaining)
                try:
                    reply, peer = sock.recvfrom(2048)
                except socket.timeout:
                    break
                if peer == (collector_ip, udp_port) and reply in (
                    b"rsp>server=1;", b"rsp>server=2;",
                ):
                    return reply
    return None


async def run(args, controls, windows):
    validate_connection_options(args)
    selected = set(args.control)
    if selected - {control.key for control in controls}:
        raise ValueError("unknown --control")
    if args.write and not selected:
        raise ValueError("--write requires explicit --control; there is no write-all mode")
    if args.write and any(control.key in selected and not control.writable for control in controls):
        raise ValueError("an excluded control was selected; no connection or writes attempted")
    if args.write and any(
        control.key in selected and control.kind in {"u16", "scaled_u16"}
        and control.key not in windows for control in controls
    ):
        raise ValueError("every numeric --control requires its owner-approved --window")
    if windows.keys() - selected:
        raise ValueError("--window must correspond to a selected --control")
    journal = Journal(Path(args.report))  # existing reports are never overwritten
    connected = asyncio.get_running_loop().create_future()

    async def accept(reader, writer):
        if connected.done() or writer.get_extra_info("peername")[0] != args.peer_ip:
            print(f"Rejected extra/unexpected collector connection from {writer.get_extra_info('peername')}", flush=True)
            writer.close()
            await writer.wait_closed()
            return
        connected.set_result(Wire(reader, writer, args.timeout))

    server = None
    wire = None
    redirect_attempted = False
    try:
        server = await asyncio.start_server(accept, args.listen, args.port)
        print(f"Waiting for {args.transport} collector {args.peer_ip} at {args.listen}:{args.port}; mode={'WRITE' if args.write else 'READ ONLY'}", flush=True)
        if args.transport == "wifi":
            # Save the return endpoint before even the first network mutation.
            journal.record("callback_original_saved", collector_ip=args.peer_ip,
                           host=args.return_host, port=args.return_port)
            redirect_attempted = True
            reply = await asyncio.to_thread(
                redirect_wifi, args.listen, args.peer_ip, args.listen, args.port)
            journal.record("callback_redirect_sent", host=args.listen, port=args.port,
                           udp_reply=reply.decode("ascii") if reply else None)
            print(f"UDP redirect reply: {reply.decode('ascii') if reply else 'none (TCP callback still awaited)'}", flush=True)
        wire = await asyncio.wait_for(connected, args.connect_timeout)
        await wire.identify(args.pn)
        journal.record("identity_verified", pn=args.pn, product_info=PRODUCT_INFO,
                       transport=args.transport)
        failures = 0
        passed = 0
        skipped_selected = 0
        for control in controls:
            if not args.write or control.key not in selected:
                journal.record("SKIPPED", key=control.key, reason="not selected for writing")
                continue
            try:
                original = (await wire.read(control.register))[0]
                candidate = control.candidate(original, windows.get(control.key))
                print(f"{control.key} @0x{control.register:04X}: {control.value(original)} -> {control.value(candidate)} -> {control.value(original)}; raw {original} -> {candidate} -> {original}")
                print("Source switching/charging settings can affect live loads. Check the inverter display.")
                if input(f"Type exactly '{control.key}' to authorize this one round trip: ").strip() != control.key:
                    journal.record("SKIPPED", key=control.key, reason="operator did not confirm")
                    skipped_selected += 1
                    continue
                await round_trip(wire, control, original, candidate, journal, args.pn,
                                 settle_seconds=args.settle_seconds)
                passed += 1
                print(f"PASS {control.key}: exact original register value restored")
            except RestoreError:
                raise
            except Exception as exc:
                failures += 1
                journal.record("FAILED", key=control.key, error=str(exc))
                # Stop after the first failure; don't compound an uncertain state.
                print(f"FAILED {control.key}: {exc}; remaining controls not tested")
                break
        if not args.write:
            for control in controls:
                try:
                    word = (await wire.read(control.register))[0]
                    journal.record("READ", key=control.key, register=control.register, raw=word)
                    print(f"{control.key}: raw={word}; write-test={'eligible' if control.writable else 'excluded'}")
                except Exception as exc:
                    failures += 1
                    journal.record("READ_FAILED", key=control.key, error=str(exc))
        journal.record("finished", failures=failures, writes_requested=args.write,
                       passed_round_trips=passed, selected=len(selected),
                       skipped_selected=skipped_selected)
        print(f"Finished: {passed} write round trips passed; {failures} failures; {skipped_selected} selected controls skipped.")
        return 1 if failures else (3 if args.write and skipped_selected else 0)
    finally:
        try:
            if server is not None:
                server.close()
            if wire is not None:
                wire.writer.close()
                await asyncio.wait_for(wire.writer.wait_closed(), args.timeout)
            if server is not None:
                await asyncio.wait_for(server.wait_closed(), args.timeout)
        finally:
            try:
                if redirect_attempted:
                    try:
                        reply = await asyncio.to_thread(
                            redirect_wifi, args.listen, args.peer_ip, args.return_host, args.return_port)
                        journal.record("callback_return_sent", host=args.return_host,
                                       port=args.return_port, verified=False,
                                       udp_reply=reply.decode("ascii") if reply else None)
                        print("Original callback requested via UDP; re-enable EyeBond Local and verify telemetry. UDP delivery is not guaranteed.")
                    except Exception as exc:
                        journal.record("CALLBACK_RETURN_FAILED", host=args.return_host,
                                       port=args.return_port, error=str(exc))
                        raise RuntimeError("Callback return failed: restore the original endpoint manually") from exc
            finally:
                journal.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transport", choices=("usb-bridge", "wifi"), default="usb-bridge")
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--listen", required=True, help="Ubuntu host LAN IPv4 address")
    parser.add_argument("--peer-ip", required=True, help="collector source IPv4: HAOS VM for Bridge, Wi-Fi collector for wifi")
    parser.add_argument("--pn", required=True, help="exact existing collector PN (not inverter serial)")
    parser.add_argument("--return-host", help="wifi: original local callback IPv4 to request after testing")
    parser.add_argument("--return-port", type=int, help="wifi: original local callback TCP port")
    parser.add_argument("--port", type=int, default=8898)
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--connect-timeout", type=float, default=120)
    parser.add_argument("--settle-seconds", type=float, default=1,
                        help="delay before verification reads (0.1..10 seconds)")
    parser.add_argument("--report", required=True, help="new durable JSONL report path")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--control", action="append", default=[])
    parser.add_argument("--window", action="append", default=[], metavar="KEY:MIN:MAX")
    args = parser.parse_args()
    try:
        validate_connection_options(args)
    except ValueError as exc:
        parser.error(str(exc))
    if not 1 <= args.port <= 65535 or any(
        not math.isfinite(value) or value <= 0 for value in (args.timeout, args.connect_timeout)
    ):
        parser.error("invalid port/timeout")
    if not math.isfinite(args.settle_seconds) or not 0.1 <= args.settle_seconds <= 10:
        parser.error("--settle-seconds must be 0.1..10")
    try:
        return asyncio.run(run(args, load_controls(args.profile), parse_windows(args.window)))
    except KeyboardInterrupt:
        print("Interrupted. Check the journal for original_restored; restoration is NOT guaranteed after power/network loss.")
        return 130
    except Exception as exc:
        print(f"STOP: {type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
