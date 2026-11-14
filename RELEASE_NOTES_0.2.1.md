# iSolar EyeBond USB Bridge 0.2.1

Version 0.2.1 of the iSolar EyeBond USB Bridge for Home Assistant.

This community app connects supported USB serial inverters to the
[EyeBond Local](https://github.com/groove-max/ha-eybond-local)
integration without requiring a separate Wi-Fi collector.

## Highlights

- USB-to-EyeBond collector emulation for Home Assistant.
- Collector discovery, heartbeat and callback handling.
- Serial connection and baud-rate configuration.
- Improved protocol framing and reconnection handling.
- Persistent USB serial device path support.
- Prebuilt Docker images for amd64 and aarch64.

## Verified compatibility

Successfully tested on an existing Home Assistant OS installation
with an EASUN iSolar SMX-II 3.6 kW / 24 V inverter.

Verified behavior:

- Home Assistant app upgraded from 0.2.0 to 0.2.1.
- Published GHCR image installed and started successfully.
- Persistent USB serial device path retained.
- Connection established with the EyeBond Local listener.
- Initial EyeBond heartbeat sent successfully.
- Inverter identified as SRNE SR-2206260036-300917.
- Collector PN V0000000000000 retained.
- Battery, grid, load and temperature telemetry available
  through EyeBond Local.

The integration identified the device using:

- Protocol family: srne_modbus
- Protocol variant: smx_ii_24v
- Register schema: srne_modbus/smx_ii_24v.json

## Build and validation

Release source commit:

`89bce301da50fe1aa9e027b2bd7fa776b049dce0`

Completed successfully:

- Python 3.12 and Python 3.13 CI checks.
- Native amd64 and aarch64 container build checks.
- GitHub CodeQL analysis for Python and GitHub Actions.
- Release workflow validation.
- GHCR image publication for both supported architectures.
- Multi-architecture OCI image manifest verification.

Container image:

`ghcr.io/tac2sc/isolar-eybond-bridge-addon:0.2.1`

Published manifest digest:

`sha256:c3daf997bd3f678a16c4189a434e7c449a9836483a96a9b55cc3afb25b72138e`

## Compatibility and limitations

The bridge handles USB serial communication and EyeBond network
transport. Inverter-specific Modbus decoding and authorization
of writable settings are implemented in EyeBond Local.

The EASUN SMX-II 24 V telemetry schema was introduced in
EyeBond Local PR #91. A compatible integration version is required.

The 36 control capabilities proposed in EyeBond Local PR #96
are not part of this bridge release. Two control capabilities
were physically tested using the stock Wi-Fi collector.
End-to-end write/readback testing through this USB bridge
has not been established for all controls.

Additional limitations:

- Automated protocol tests use simulated serial responses.
- A fresh Home Assistant OS installation has not been
  independently verified.
- Compatibility with every inverter model and firmware
  version is not guaranteed.
- The EyeBond network protocol is unauthenticated.
  Use only on trusted networks. Do not expose the relevant
  ports directly to the Internet.

## Documentation

- [Installation and migration](isolar_eybond_usb_bridge/DOCS.md)
- [Hardware testing](HARDWARE_TEST.md)
- [SMX-II interoperability](docs/SMX_II_24V_INTEROP.md)
- [Security](SECURITY.md)

This is an independent community project, not affiliated with
or endorsed by Home Assistant, EyeBond or the inverter manufacturer.
