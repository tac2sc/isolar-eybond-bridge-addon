# Supervised SMX-II control tests

`tools/hardware_controls.py` checks real setting writes **through USB Bridge or
a stock EyeBond/SmartESS Wi-Fi collector with local EyeBond forwarding**.
It is not executed against hardware by CI. CI runs simulated safety tests only.
The test does not mark skipped commands as tested and does not claim that all
settings or all inverter models are safe to write.

## Supported device and safety boundary

- Only the owner-identified SMX-II 3.6 kW / 24 V unit is accepted: exact 20-byte
  Modbus product-info `SR-2206260036-300917`. Other units receive no writes.
- The runner requires the exact collector PN and the expected TCP peer IPv4.
- Register definitions come from the separate EyeBond Local SMX-II profile.
  Bridge still has no built-in inverter register map.
- Default mode only reads settings. Real writes require `--write`, explicit
  `--control` keys, and typing the name before **each** round trip.
- Numeric controls also require an owner-approved `--window KEY:MIN:MAX`, in
  displayed engineering units, containing the original and adjacent value.
  Profile limits are not a battery/load safety recommendation. Consult the
  battery and inverter specifications before choosing a window.
- One profile step is used, preferably downward. Enums move to one adjacent
  listed option; booleans toggle. An adjacent option can switch the power or
  charging source: it is not necessarily a small physical change.
- Power, battery chemistry/type, output frequency, equalization activation,
  power-saving and protection/restart toggles are excluded. Unknown/new register
  mappings, masked and multiword writes are excluded as well.
- Password registers and automatic default-password login are never used.
  Permission-denied replies remain failures, not successful tests.
- Do not test while loss of power would endanger anyone or interrupt important
  loads. Do not leave the test unattended. Make a HA backup and record settings
  on the inverter display before beginning.

## Temporary USB Bridge connection arrangement

The runner listens on the **Ubuntu host**, normally port **8898**. It receives
the reverse TCP connection from the existing Bridge in the HAOS VM. It does not
open the USB adapter directly and does not run a second serial bridge.

1. Record the Bridge's existing `ha_host`, `ha_port` and `collector_pn`/PN.
2. Stop the Bridge app. Disable the EyeBond Local integration entry during the
   test so discovery or automation cannot compete with the test session. Stop
   any other software using this USB adapter. The USB remains passed to HAOS.
3. Temporarily set the Bridge's `ha_host` to the Ubuntu host LAN IPv4 and
   `ha_port` to `8898`. Keep its PN, serial path and baud unchanged. Keep
   `allow_remote_redirect` false. Do not start it until the runner is waiting.
4. Run the command below on Ubuntu, then start the Bridge app. The runner's
   `--peer-ip` must be the source IP of the HAOS VM connection. QEMU NAT may
   change the visible source IP; a mismatch is printed and rejected, never
   accepted automatically. Both IPs and the port must be reachable on your
   trusted LAN. Do not expose this unauthenticated listener to the Internet.
5. After the run, stop the Bridge app, restore the original `ha_host`/`ha_port`,
   start it and re-enable the integration entry. Verify telemetry has returned.
   Do this even if the test failed. The runner does not alter endpoint settings.

## Ubuntu preparation and read-only inventory

Use the activated virtual environment from the Bridge development setup.
The separate integration checkout must also exist on Ubuntu and contain the
SMX-II profile. The previously used checkout is `~/ha-eybond-local`.

```bash
cd ~/isolar-eybond-bridge-addon
source .venv/bin/activate
PROFILE="$HOME/ha-eybond-local/custom_components/eybond_local/protocol_catalogs/profiles/srne_modbus/smx_ii.json"
test -f "$PROFILE"
```

Substitute your actual Ubuntu/HAOS IPs and exact PN for these placeholders:

```bash
python tools/hardware_controls.py \
  --profile "$PROFILE" \
  --listen UBUNTU_LAN_IP --peer-ip HAOS_LAN_IP --pn YOUR_EXISTING_PN \
  --report smx-read-only.jsonl
```

This performs identification and reads the profile's registers without writing.
Unreadable registers are reported as failures, not invented values. A new
report path is required for each run; existing reports are never overwritten.

## One supervised write test

An alarm-setting toggle is a possible first test if the owner approves briefly
changing audible alarms; it is not a guarantee of safety for every installation.

```bash
python tools/hardware_controls.py \
  --profile "$PROFILE" \
  --listen UBUNTU_LAN_IP --peer-ip HAOS_LAN_IP --pn YOUR_EXISTING_PN \
  --write --control input_change_alarm \
  --report smx-input-change-alarm.jsonl
```

Before writing, the runner prints the register, original, candidate and restore
value. Check these against the inverter display. Type `input_change_alarm` only
if this specific change is acceptable. Any other input skips the command.

For a numeric setting, append `--control KEY --window KEY:MIN:MAX` using an
interval approved for **your** battery/load. No example voltage/current bounds
are supplied intentionally. You may repeat `--control` and `--window`; there
is no `--all` or unattended confirmation option.

## Stock Wi-Fi collector (same SMX-II unit)

Use `--transport wifi` for a stock collector that supports EyeBond Local's
UDP discovery and FC4 Modbus forwarding. This is not a generic test for any
Wi-Fi dongle, a cloud API, or another inverter. The exact inverter identity and
SMX-II profile restrictions above are unchanged. A different inverter receives
no writes. An unsupported protocol/route fails; the runner never guesses an
alternative register map, serial speed, password or control protocol.

No USB Bridge is needed in this mode. The Wi-Fi collector itself opens the
reverse TCP connection to the test listener. The runner sends **only targeted
UDP** `set>server=IP:PORT;` discovery variants to that collector's IPv4 on port
58899. The UDP source socket remains open while awaiting the reply: each format
gets up to one second, and the next format is sent only after a timeout. Replies
are accepted only from that collector's IP/UDP port and must be
`rsp>server=1;` or `rsp>server=2;`. This avoids closing the socket before the
reply and causing host-generated ICMP port-unreachable messages. The wait runs
outside the event loop so the TCP listener remains responsive. Console and
JSONL records include the UDP reply (or its absence); it is not TCP confirmation.
The same FC2 PN query and FC4 route used by EyeBond Local's SRNE driver
are used: devcode 1, collector address 255, Modbus slave 1. A truncated heartbeat
PN is not accepted as the full identity; FC2 must return the exact supplied PN.
Trailing NUL padding in that reply is supported. The PN query checks the reply's
TID and FC2, but does not require its device code/address to echo the query:
the owner's stock collector returns code `0x0102`, address `0xFF` to a query
sent with code `0`, address `1`. Exact PN and inverter identity checks are still
required; route matching for forwarded Modbus responses is unchanged.

### Preparation

1. Confirm this is the same SMX-II unit, record its settings on the display and
   identify the **Wi-Fi collector's** full PN and LAN IPv4 in EyeBond Local's
   diagnostics. Its PN is different from a virtual USB Bridge PN and from the
   inverter serial. Do not reuse the Bridge PN.
2. Record the original **local callback** address/port from the integration
   configuration. Supply them as `--return-host` and `--return-port`; do not
   assume port 8899. The runner requires an IPv4 address, not a cloud domain.
   If only a cloud-only connection exists and no known local callback is
   available, this procedure is not applicable without separate setup.
3. Disable the EyeBond Local integration entry and any competing discovery,
   cloud control or local automation. Stop the USB Bridge and other serial
   masters while using the stock collector; no parallel USB polling/writes.
   Keep the collector powered and connected through its normal Wi-Fi/inverter
   connection. Do not change its UART settings or persistent server settings.
4. Run on the Ubuntu host in the same trusted LAN. Allow TCP 8899 inbound from
   the collector, and UDP 58899 outbound to it. `--peer-ip` is now the physical
   collector IP, **not** the HAOS VM. Do not expose the listener to the Internet.

The owner's stock collector was observed to connect to the Ubuntu listener on
8899, but not 8898. Use explicit `--port 8899` for this unit (the unchanged USB
Bridge default is 8898). First check `ss -lntp 'sport = :8899'` on Ubuntu: if the
port is occupied, do not stop that service or assume another port will work.
This observation is not a universal firmware port restriction.

Use the same `PROFILE` variable prepared above. Replace all placeholders with
the verified addresses, full stock collector PN and original local TCP port:

```bash
python tools/hardware_controls.py \
  --transport wifi --profile "$PROFILE" --port 8899 \
  --listen UBUNTU_LAN_IP --peer-ip WIFI_COLLECTOR_IP --pn STOCK_COLLECTOR_PN \
  --return-host ORIGINAL_HA_CALLBACK_IP --return-port ORIGINAL_HA_CALLBACK_PORT \
  --report smx-wifi-read-only.jsonl
```

Begin with this read-only inventory. Only after it succeeds, and if the owner
approves a temporary change to audible alarms, use a separate report for the
supervised write/readback/restore test:

```bash
python tools/hardware_controls.py \
  --transport wifi --profile "$PROFILE" --port 8899 \
  --listen UBUNTU_LAN_IP --peer-ip WIFI_COLLECTOR_IP --pn STOCK_COLLECTOR_PN \
  --return-host ORIGINAL_HA_CALLBACK_IP --return-port ORIGINAL_HA_CALLBACK_PORT \
  --write --control input_change_alarm \
  --report smx-wifi-input-change-alarm.jsonl
```

Numeric controls still need an approved `--window KEY:MIN:MAX`; every round
trip needs typed confirmation. Hazardous/excluded controls remain excluded.

The original callback is saved durably before the first UDP redirect. On normal
completion, setup failure, timeout or interruption the runner attempts to send
the original callback again, **after** any register restoration. It sends no
persistent FC3/AT endpoint writes or reboot commands. UDP delivery is not
guaranteed; firmware may handle or retain discovery differently. A
`callback_return_sent` event has `verified: false` and does **not** prove that
Home Assistant reconnected. `CALLBACK_RETURN_FAILED` is fatal.

After **every** run, re-enable the integration and verify fresh telemetry.
If it does not reconnect, use the integration's existing discovery/setup
procedure to reclaim the original local callback. After power loss or process
kill automatic return may not run at all. Check both the register-restoration
journal and the original network connection before returning to normal use.

Local automated tests simulate a stock-style collector over real loopback
UDP/TCP sockets. They check the successful round trip, read-only mode, wrong PN,
wrong inverter identity, readback mismatch, lost acknowledgement/connection,
rejected register restoration and return request/failure on timeout. They
are not evidence of a successful physical Wi-Fi collector test.

## What a PASS means

1. Live collector and exact inverter identity are checked.
2. The setting is reread and must equal the confirmed original.
3. Raw original and candidate words are flushed and synced to the JSONL journal
   **before the first write**.
4. Exactly one FC06 setting write is sent, with no write retries.
5. After a settling delay, the exact acknowledgement and a fresh FC03 register
   read must match. `--settle-seconds` defaults to 1 second (allowed: 0.1..10).
6. Identity is checked again, then the original is written back. Two fresh
   reads, each after the settling delay, must confirm the original value.
7. `PASS` is recorded only after the original raw word is confirmed restored.

A lost acknowledgement can mean the write happened. The runner attempts
restoration even on a write error or interruption. If a valid read shows an
unexpected third value, it stops rather than overwriting a possible external
change. The first failure stops further write tests.

**Restoration cannot be guaranteed after a power/network loss or process kill.**
The runner closes a damaged/timed-out connection rather than accepting stale
frames. In that case `RESTORE_FAILED` is fatal: inspect the saved `original`
and `register` in the journal and restore the setting manually on the display
before resuming normal operation. Repeated Ctrl+C or killing the process can
also prevent cleanup. Do not interpret a missing `original_restored` as success.

A PASS proves that one target register changed and returned to its original
word. It does not prove that firmware caused no collateral changes to other
settings. Check the display/settings after testing; compare a Support Archive
before and after the session if available.

Exit codes: `0` successful requested operation (read-only is not write-tested),
`1` setting/read failure, `2` fatal/setup/restoration failure, `3` selected write
tests skipped by the operator, `130` interrupted. Inspect the JSONL records for
actual `PASS`, `FAILED`, `SKIPPED` and `RESTORE_FAILED` events. Reports include
device identity: review/redact PN/serial before publishing them on GitHub.

The command and report describe the specific hardware run. CI success alone
must never be relabeled as a real-inverter test.
