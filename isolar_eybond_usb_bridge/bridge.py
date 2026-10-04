#!/usr/bin/env python3
"""Linux serial-to-EyeBond bridge compatible with ha-eybond-local.

The wire format and behavior mirror groove-max/esp-eybond-collector: an
outbound TCP collector connection, UDP `set>server` discovery, FC=1/2/3
collector requests, and transparent FC=4 serial forwarding.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
import re
import signal
import struct
import ipaddress
import secrets
import time
from pathlib import Path
from dataclasses import dataclass

import serial

LOG = logging.getLogger("isolar-eybond-bridge")
HEADER = struct.Struct(">HHHBB")
HEADER_SIZE = HEADER.size
MAX_PAYLOAD = 512
MAX_AT_LINE = 256
FRAME_TIMEOUT = 10.0
FC_HEARTBEAT, FC_QUERY, FC_SET, FC_FORWARD = 1, 2, 3, 4
DISCOVERY_REPLY = b"rsp>server=2;"
PN_RE = re.compile(r"^[A-Z][0-9]{13}(?:[0-9]{4})?$")


def collector_identity(configured: str, data_dir: str) -> str:
    """Keep an explicit PN on upgrades; persist a random one for new installs."""
    if configured:
        if not PN_RE.fullmatch(configured):
            raise ValueError("invalid collector PN")
        return configured
    path = Path(data_dir) / "collector_pn"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        try:
            with path.open("x", encoding="ascii") as stream:
                stream.write(f"V{secrets.randbelow(10**13):013d}\n")
        except FileExistsError:
            pass
    value = path.read_text(encoding="ascii").strip()
    if not PN_RE.fullmatch(value):
        raise ValueError("invalid persisted collector identity; restore its backup")
    return value


def endpoint_valid(host: str, port: int) -> bool:
    try:
        address = ipaddress.IPv4Address(host)
    except ipaddress.AddressValueError:
        return False
    return 1 <= port <= 65535 and not (
        address.is_multicast or address.is_unspecified or int(address) == 0xFFFFFFFF
    )


async def read_message(reader: asyncio.StreamReader) -> Frame | bytes:
    # Idle connections are allowed; once a message starts, completion is bounded.
    first = await reader.readexactly(1)

    async def remainder() -> Frame | bytes:
        prefix = first + await reader.readexactly(2)
        if prefix == b"AT+":
            line = bytearray(prefix)
            while len(line) < MAX_AT_LINE:
                line.extend(await reader.readexactly(1))
                if line.endswith(b"\n"):
                    return bytes(line)
            raise ValueError("AT line exceeds 256 bytes")
        header = prefix + await reader.readexactly(HEADER_SIZE - 3)
        tid, devcode, wire_len, addr, fcode = HEADER.unpack(header)
        if not 2 <= wire_len <= MAX_PAYLOAD + 2:
            raise ValueError(f"invalid EyeBond header: {header.hex()}")
        payload = await reader.readexactly(wire_len - 2)
        return Frame(tid, devcode, addr, fcode, payload)

    return await asyncio.wait_for(remainder(), timeout=FRAME_TIMEOUT)


def build_frame(tid: int, devcode: int, addr: int, fcode: int, payload: bytes) -> bytes:
    """Encode the exact EyeBond header: tid, devcode, total_len-6, addr, fc."""
    return HEADER.pack(tid, devcode, HEADER_SIZE + len(payload) - 6, addr, fcode) + payload


@dataclass(frozen=True)
class Frame:
    tid: int
    devcode: int
    addr: int
    fcode: int
    payload: bytes


class DiscoveryProtocol(asyncio.DatagramProtocol):
    def __init__(self, bridge: "Bridge") -> None:
        self.bridge = bridge
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, peer: tuple[str, int]) -> None:
        if len(data) > 256:
            return
        match = re.fullmatch(rb"\s*set>server=([^:\s;]+):(\d+);\s*", data)
        if not match:
            return
        host, port_text = match.groups()
        try:
            host_text, port = host.decode("ascii"), int(port_text)
        except (ValueError, UnicodeDecodeError):
            return
        if not endpoint_valid(host_text, port):
            return
        # Default configuration pins the callback target. UDP has no auth.
        if self.bridge.endpoint and (host_text, port) != self.bridge.endpoint:
            if not getattr(self.bridge.args, "allow_remote_redirect", False):
                return
        elif not self.bridge.endpoint and host_text != peer[0]:
            return
        assert self.transport is not None
        self.transport.sendto(DISCOVERY_REPLY, peer)
        self.bridge.set_endpoint(host_text, port, source="UDP discovery")


class Bridge:
    def __init__(self, args: argparse.Namespace) -> None:
        if not PN_RE.fullmatch(args.pn):
            raise ValueError("--pn must be one uppercase letter plus 13 or 17 digits")
        self.args = args
        self.baud = int(getattr(args, "baud", 9600))
        if self.baud not in (2400, 4800, 9600, 19200):
            raise ValueError("--baud must be one of 2400, 4800, 9600, 19200")
        self.heartbeat_interval = float(getattr(args, "heartbeat_interval", 60.0))
        if self.heartbeat_interval <= 0:
            raise ValueError("--heartbeat-interval must be greater than zero")
        self.endpoint: tuple[str, int] | None = (
            (args.ha_host, args.ha_port) if args.ha_host else None
        )
        if self.endpoint and not endpoint_valid(*self.endpoint):
            raise ValueError("HA host must be an IPv4 address and port must be 1..65535")
        self.serial_lock = asyncio.Lock()
        self.stop = asyncio.Event()
        self.callback_requested = asyncio.Event()
        self.active_writer: asyncio.StreamWriter | None = None
        self.unsolicited_tid = 0x8000
        self.pending_endpoint: tuple[str, int] | None = None
        self.restart_after_reply = False

    def request_stop(self) -> None:
        self.stop.set()
        self.callback_requested.set()
        if self.active_writer is not None:
            self.active_writer.close()

    def set_endpoint(self, host: str, port: int, *, source: str) -> None:
        endpoint = (host, port)
        if self.endpoint != endpoint:
            LOG.info("Home Assistant endpoint set to %s:%d via %s", host, port, source)
            self.endpoint = endpoint
        # A UDP set>server datagram is not merely configuration: EyeBond Local
        # uses the *new connection caused by that datagram* as onboarding proof.
        # Therefore even an unchanged endpoint must replace the current socket.
        if source == "UDP discovery":
            LOG.info("fresh Home Assistant callback requested by UDP discovery")
            self.callback_requested.set()
            if self.active_writer is not None:
                self.active_writer.close()

    async def serial_exchange(self, request: bytes) -> bytes:
        """Send exactly one raw RTU request and return bytes after 60 ms silence.

        A 3 s no-first-byte deadline and no fabricated response match the ESP
        collector's UART contract.  The lock guarantees a single Modbus master.
        """
        async with self.serial_lock:
            return await asyncio.to_thread(self._serial_exchange_blocking, request)

    def _serial_exchange_blocking(self, request: bytes) -> bytes:
        with serial.Serial(
            self.args.serial_device,
            baudrate=self.baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.06,
            write_timeout=1,
            exclusive=True,
        ) as port:
            port.reset_input_buffer()
            port.write(request)
            data = bytearray()
            # 50 reads x 60 ms = 3 seconds before the first received byte.
            for _ in range(50):
                chunk = port.read(512)
                if chunk:
                    data.extend(chunk)
                    break
            if not data:
                LOG.warning("inverter did not answer request: %s", request.hex())
                return b""
            deadline = time.monotonic() + 3
            while len(data) <= MAX_PAYLOAD and time.monotonic() < deadline:
                chunk = port.read(512)
                if not chunk:
                    return bytes(data)
                data.extend(chunk)
            LOG.warning("discarding oversized or unterminated serial response")
            return b""

    def heartbeat(self, tid: int) -> bytes:
        return build_frame(tid, 0, 1, FC_HEARTBEAT, self.args.pn[:14].encode().ljust(14, b"\0"))

    async def heartbeat_loop(self, writer: asyncio.StreamWriter) -> None:
        """Keep the HA route and collector identity fresh like the ESP core."""
        try:
            while not self.stop.is_set() and not writer.is_closing():
                await asyncio.sleep(self.heartbeat_interval)
                if self.stop.is_set() or writer.is_closing():
                    return
                tid = self.next_tid()
                writer.write(self.heartbeat(tid))
                await writer.drain()
                LOG.debug("sent periodic EyeBond heartbeat tid=0x%04x", tid)
        except (ConnectionError, OSError) as exc:
            LOG.info("HA heartbeat stopped: %s", exc)
            writer.close()

    def query(self, frame: Frame) -> bytes:
        parameter = frame.payload[0] if frame.payload else 0
        answers = {
            2: self.args.pn,
            5: self.args.version,
            6: f"esp-collector/{self.args.version}/Linux",
            21: f"{self.endpoint[0]},{self.endpoint[1]},TCP" if self.endpoint else "",
            34: str(self.baud),
        }
        if parameter in answers:
            payload = bytes((0, parameter)) + answers[parameter].encode("ascii")
        else:
            payload = bytes((1, parameter))
        return build_frame(frame.tid, frame.devcode, frame.addr, FC_QUERY, payload)

    def handle_set(self, frame: Frame) -> bytes:
        """Handle the supported collector-management writes.

        ESP EyeBond Collector accepts FC=3 parameter 29 as the confirmation for
        a restart/apply operation even when no endpoint is staged.  EyeBond
        Local requires that exact ``status=0, parameter=29`` acknowledgement
        while onboarding a local-only bridge.
        """
        parameter = frame.payload[0] if frame.payload else 0
        value = frame.payload[1:].decode("ascii", errors="ignore")
        status = 1
        if parameter == 21:  # staged ``host,port,TCP`` endpoint
            parts = value.removesuffix(",TCP").rsplit(",", 1)
            if (
                len(parts) == 2 and parts[1].isdigit()
                and endpoint_valid(parts[0], int(parts[1]))
                and (
                    (parts[0], int(parts[1])) == self.endpoint
                    or getattr(self.args, "allow_remote_redirect", False)
                )
            ):
                self.pending_endpoint = (parts[0], int(parts[1]))
                status = 0
        elif parameter == 29:  # apply/restart confirmation
            if self.pending_endpoint:
                self.set_endpoint(*self.pending_endpoint, source="FC=3 apply")
                self.pending_endpoint = None
            status = 0
            # The response must be flushed on the current socket first.  The
            # connection handler closes it immediately afterwards so HA sees
            # the fresh callback required by the onboarding transaction.
            self.restart_after_reply = True
        elif parameter == 34:  # inverter UART baud rate
            try:
                baud = int(value)
            except ValueError:
                baud = 0
            if baud in (2400, 4800, 9600, 19200):
                if baud != self.baud:
                    LOG.info("inverter UART baud rate changed from %d to %d", self.baud, baud)
                    self.baud = baud
                status = 0
        return build_frame(frame.tid, frame.devcode, frame.addr, FC_SET, bytes((status, parameter)))

    def at_reply(self, raw: bytes) -> bytes | None:
        try:
            line = raw.decode("ascii").strip()
        except UnicodeDecodeError:
            return None
        if not line.startswith("AT+"):
            return None
        body = line[3:]
        command = body.rstrip("?=").split("=", 1)[0].upper()
        if "=" in body:
            value = body.split("=", 1)[1]
            if command == "UART":
                fields = value.split(",")
                if len(fields) != 4 or fields[1:] != ["8", "1", "NONE"]:
                    return None
                if fields[0] not in ("2400", "4800", "9600", "19200"):
                    return None
                self.baud = int(fields[0])
            elif command == "CLDSRVHOST1":
                parts = value.removesuffix(",TCP").rsplit(",", 1)
                if len(parts) != 2 or not parts[1].isdigit():
                    return None
                target = (parts[0], int(parts[1]))
                if not endpoint_valid(*target):
                    return None
                if target != self.endpoint and not getattr(self.args, "allow_remote_redirect", False):
                    return None
                self.set_endpoint(*target, source="AT endpoint")
                self.restart_after_reply = True
            else:
                # No documented error code: silence is preferable to false W000.
                return None
            return f"AT+{command}:W000\r\n".encode()
        values = {
            "DTUPN": self.args.pn, "ATVER": "1.11", "ENUPMODE": "OFF",
            "UART": f"{self.baud},8,1,NONE", "DTUTYPE": "Linux USB Bridge",
            "FWVER": self.args.version, "LINK": "connected", "HTBT": "",
            "CLDSRVHOST1": f"{self.endpoint[0]},{self.endpoint[1]},TCP" if self.endpoint else "",
        }
        return f"AT+{command}:{values.get(command, '')}\r\n".encode()

    async def handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        LOG.info("connected to HA listener %s", peer)
        self.active_writer = writer
        try:
            await self.serve_connection(reader, writer)
        finally:
            if self.active_writer is writer:
                self.active_writer = None
            writer.close()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(writer.wait_closed(), 2)

    async def serve_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        initial_tid = self.next_tid()
        writer.write(self.heartbeat(initial_tid))
        await writer.drain()
        LOG.info(
            "sent initial EyeBond heartbeat pn=%s tid=0x%04x",
            self.args.pn[:14],
            initial_tid,
        )
        heartbeat_task = asyncio.create_task(
            self.heartbeat_loop(writer),
            name="eybond_periodic_heartbeat",
        )
        try:
            while not self.stop.is_set():
                message = await read_message(reader)
                if isinstance(message, bytes):
                    reply = self.at_reply(message)
                    if reply:
                        writer.write(reply)
                        await writer.drain()
                    if self.restart_after_reply:
                        self.restart_after_reply = False
                        self.callback_requested.set()
                        return
                    continue
                frame = message
                if frame.fcode == FC_HEARTBEAT:
                    reply = self.heartbeat(frame.tid)
                elif frame.fcode == FC_QUERY:
                    reply = self.query(frame)
                elif frame.fcode == FC_SET:
                    reply = self.handle_set(frame)
                elif frame.fcode == FC_FORWARD:
                    response = await self.serial_exchange(frame.payload)
                    if not response:  # Exact collector semantic: silence produces no TCP reply.
                        continue
                    reply = build_frame(frame.tid, frame.devcode, frame.addr, FC_FORWARD, response)
                else:
                    continue
                writer.write(reply)
                await writer.drain()
                if self.restart_after_reply:
                    self.restart_after_reply = False
                    self.callback_requested.set()
                    LOG.info("restart request acknowledged; reconnecting to HA listener")
                    return
        except (ValueError, asyncio.TimeoutError) as exc:
            # Protocol desynchronisation is scoped to this TCP connection.
            # The ESP reference collector closes and reconnects; letting this
            # escape would instead terminate and restart the whole container.
            LOG.warning("HA protocol error; dropping connection: %s", exc)
        except (asyncio.IncompleteReadError, ConnectionError, OSError) as exc:
            LOG.info("HA connection closed: %s", exc)
        finally:
            heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat_task

    def next_tid(self) -> int:
        self.unsolicited_tid = (self.unsolicited_tid + 1) & 0xFFFF
        if self.unsolicited_tid < 0x8000:
            self.unsolicited_tid = 0x8000
        return self.unsolicited_tid

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: DiscoveryProtocol(self), local_addr=("0.0.0.0", self.args.udp_port), allow_broadcast=True
        )
        try:
            while not self.stop.is_set():
                if not self.endpoint:
                    await asyncio.sleep(1)
                    continue
                host, port = self.endpoint
                try:
                    reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), 10)
                    await self.handle_connection(reader, writer)
                except (OSError, asyncio.TimeoutError) as exc:
                    LOG.warning("cannot connect to HA listener %s:%s: %s", host, port, exc)
                # Discovery-triggered callbacks are causal and must be prompt;
                # normal failures retain a small reconnect backoff.
                if self.callback_requested.is_set():
                    self.callback_requested.clear()
                    continue
                try:
                    await asyncio.wait_for(self.callback_requested.wait(), timeout=2)
                    self.callback_requested.clear()
                except asyncio.TimeoutError:
                    pass
        finally:
            transport.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial-device", default=os.getenv("SERIAL_DEVICE", "/dev/ttyUSB0"))
    parser.add_argument("--ha-host", default=os.getenv("HA_HOST", ""), help="HA listener IP; optional when discovery is used")
    parser.add_argument("--ha-port", type=int, default=int(os.getenv("HA_PORT", "8899")))
    parser.add_argument("--udp-port", type=int, default=int(os.getenv("UDP_PORT", "58899")))
    parser.add_argument("--baud", type=int, default=int(os.getenv("SERIAL_BAUD", "9600")))
    parser.add_argument(
        "--heartbeat-interval",
        type=float,
        default=float(os.getenv("HEARTBEAT_INTERVAL", "60")),
        help="seconds between unsolicited EyeBond heartbeats",
    )
    parser.add_argument("--pn", default=os.getenv("COLLECTOR_PN", ""))
    parser.add_argument("--version", default=os.getenv("BRIDGE_VERSION", "0.2.1"))
    parser.add_argument("--allow-remote-redirect", action="store_true")
    parser.add_argument("--data-dir", default=os.getenv("DATA_DIR", "/data"))
    return parser.parse_args()


async def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args()
    args.pn = collector_identity(args.pn, args.data_dir)
    bridge = Bridge(args)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, bridge.request_stop)
    await bridge.run()


if __name__ == "__main__":
    asyncio.run(main())
