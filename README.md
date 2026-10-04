# iSolar EyeBond USB Bridge for Home Assistant

Community maintained Home Assistant app (formerly add-on) for an EASUN/iSolar
SMX II connected over USB serial. The app presents a network EyeBond collector
to the separately installed [EyeBond Local](https://github.com/groove-max/ha-eybond-local)
integration. It does not include the integration or a Modbus register map.

**Status:** 0.2.1 publication candidate. CI tests run without an inverter.
The author must verify a full HAOS install, serial reads and controls on real
hardware before enabling the published image in the store. This project has
not been accepted into the Home Assistant official repository.

## Install after first image release

1. Add `https://github.com/tac2sc/isolar-eybond-bridge-addon` as an app
   repository in Home Assistant Settings → Apps → Install app → repositories.
2. Install **iSolar EyeBond USB Bridge**. Select the serial device and start it.
3. Follow [app documentation](isolar_eybond_usb_bridge/DOCS.md) for integration
   setup and migration.

Until image 0.2.1 exists on GHCR, use the local build procedure in
[release checklist](RELEASE.md) and omit the `image` key from config.yaml.

## Development

```sh
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
python tools/validate.py
```

CI tests Python 3.12/3.13 and builds native amd64/aarch64 images. Bridge
wire behavior is derived from
[esp-eybond-collector](https://github.com/groove-max/esp-eybond-collector)
and [ha-eybond-local](https://github.com/groove-max/ha-eybond-local).
See [security notes](SECURITY.md), [license](LICENSE), and
[release checklist](RELEASE.md).

This community project is not affiliated with or endorsed by Home Assistant,
EyeBond or the inverter manufacturer.
