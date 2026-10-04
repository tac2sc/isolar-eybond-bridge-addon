# iSolar EyeBond USB Bridge

This app requires Home Assistant OS or Supervised with a local USB serial
adapter, plus the separately installed EyeBond Local custom integration.
It bridges raw serial requests. The inverter register schema and write policy
belong to EyeBond Local.

## Configure

Stop any other process using this adapter, including the standalone Docker
bridge. In Settings → Apps, type the serial device path. Two identical CH340
adapters may have the same `/dev/serial/by-id/...` name, so that name cannot
distinguish them. Check Settings → System → Hardware → All Hardware and
use the inverter adapter's `/dev/serial/by-path/...` path if it exists inside
the app; otherwise type its `/dev/ttyUSB0` or `/dev/ttyUSB1` path. The latter
can change after reboot or replug. A by-path name remains stable only while
the USB socket and hub layout stay the same. Use baud 9600 for the iSolar
SMX II. The integration may change this during discovery.

If the app cannot open a by-path link, use the corresponding `/dev/ttyUSBx`
device instead. Check the app log for the actual serial-open error. Do not
enter the `Bus 001 Device ...` identifier shown by `lsusb`: it is not a
serial-device path.

Set `ha_host` to Home Assistant's LAN IPv4 address, such as `10.0.0.111`,
for an immediate callback. With a fixed `ha_host`, discovery cannot redirect
the bridge to another address unless `allow_remote_redirect` is enabled.
Keep that setting off on ordinary networks. If `ha_host` is blank, the first
matching UDP discovery request supplies the callback address.

Leave `collector_pn` blank on a fresh install. The app stores a random PN
in its backed-up `/data/collector_pn`; this keeps device identity stable over
restarts. If you are upgrading a collector already in EyeBond Local, set
`collector_pn` to its previous PN (for example `V0000000000000`) before
starting the new version. Changing PN creates a new collector identity.

## Verify

Start the app. Its log should report connection to the Home Assistant listener
and an initial EyeBond heartbeat. Discover in EyeBond Local using UDP 58899
and TCP 8899. Inverter readings should appear only if the serial port and
protocol match. Check the live battery voltage against the inverter display
before enabling controls in EyeBond Local.

If the app logs `cannot connect to HA listener`, check that EyeBond Local is
listening on the chosen host and port. If it logs `inverter did not answer`,
check serial path, baud, adapter wiring and that no other process holds the
port. A silent inverter deliberately receives no fabricated response.

EyeBond TCP and UDP are unauthenticated. Do not expose these ports outside
your trusted LAN. FC4 passes raw requests, so the app does not enforce read
only access. See [security guidance](../SECURITY.md).

## Updating from 0.1.14

Stop the standalone Docker bridge or old local app. Back up Home Assistant.
Keep the existing PN in the new app's `collector_pn` option. Start the new app,
confirm the same collector device is recognized, and only then remove old
installations. Keep EyeBond Local in Read Only mode during the change.

This release uses host networking for the reverse TCP/UDP collector protocol
and Supervisor `uart: true` for serial access. It does not require privileged
mode, Home Assistant configuration access or Supervisor API tokens.
