# iSolar EyBond USB Bridge for Home Assistant

Community maintained Home Assistant app (formerly add-on) for an EASUN/iSolar
SMX II connected over USB serial. The app presents a network EyeBond collector
to the separately installed [EyeBond Local](https://github.com/groove-max/ha-eybond-local)
integration. It does not include the integration or a Modbus register map.

**Status:** 0.2.1 publication candidate. Automated checks have completed
successfully, and the project owner reports successful testing with a real
inverter. This is a community project, not an official Home Assistant app.

## Validation

- All 8 bridge unit tests passed in the reported local Linux run.
- GitHub Actions checks passed on Python 3.12 and 3.13, including publication
  metadata validation and shell syntax checks.
- Docker image builds and container tests passed for both amd64 and aarch64.
- Successful testing with a real inverter was reported by the project owner.

See [GitHub Actions](https://github.com/tac2sc/isolar-eybond-bridge-addon/actions/workflows/check.yml)
for results associated with individual commits.

Automated tests use simulated serial responses and do not require an inverter.
The hardware result is a separate owner-reported check, not a claim that every
inverter model, firmware version or writable setting has been validated.
Passing CI does not publish an image to GHCR; publication is a separate step.

For supervised real-inverter write/readback/restore checks, see
[hardware control tests](HARDWARE_TEST.md) (USB Bridge or stock local EyeBond
Wi-Fi collector, using `--transport wifi`). These tests require explicit
per-setting approval and are not run against hardware by GitHub Actions.

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
