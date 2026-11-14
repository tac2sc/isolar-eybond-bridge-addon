# iSolar EyeBond USB Bridge

Connect your EASUN/iSolar inverter to Home Assistant via USB, without a separate EyeBond Wi-Fi collector.

This Home Assistant app turns a USB-connected inverter into a virtual EyeBond collector, allowing it to work with the [EyeBond Local](https://github.com/groove-max/ha-eybond-local) integration.

The bridge handles USB communication and network transport. EyeBond Local provides sensors, inverter-specific settings and supported controls.

## Installation

1. Install the [EyeBond Local](https://github.com/groove-max/ha-eybond-local) integration in Home Assistant.
2. Open **Settings → Apps → App Store → ⋮ → Repositories**.
3. Add this repository:
   `https://github.com/tac2sc/isolar-eybond-bridge-addon`
4. Install **iSolar EyeBond USB Bridge**.
5. Select your USB serial device, configure the connection settings and start the app.
6. Check the app logs and confirm that your inverter appears in EyeBond Local.

For detailed instructions, see the [setup and migration guide](isolar_eybond_usb_bridge/DOCS.md).

**Tip:** Use a persistent serial device path such as `/dev/serial/by-path/...` instead of `/dev/ttyUSB0` when possible. It helps avoid port changes after a restart.

If you're migrating from a locally installed version, follow the migration guide rather than running two bridges simultaneously.

## Compatibility

**Tested with real hardware:**

- EASUN iSolar SMX-II 3.6 kW / 24 V
- USB serial connection on Home Assistant OS
- Live telemetry through EyeBond Local

Other compatible serial inverters may work, but have not all been tested.

Inverter-specific decoding and write permissions are handled by EyeBond Local. Not all control operations have been verified on physical hardware.

## Releases

The latest release and version history are available on the [Releases page](https://github.com/tac2sc/isolar-eybond-bridge-addon/releases).

Prebuilt Docker images are provided for **amd64** and **aarch64**.

## Documentation

- [Setup and migration](isolar_eybond_usb_bridge/DOCS.md)
- [Hardware testing](HARDWARE_TEST.md)
- [Security](SECURITY.md)
- [License](LICENSE)

This is an independent community project, not affiliated with or endorsed by Home Assistant, EyeBond or the inverter manufacturer.
