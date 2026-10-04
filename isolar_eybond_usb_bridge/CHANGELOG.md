# Changelog

## 0.2.1 (candidate)

- Serial device is now an editable path, so identical CH340 adapters can be
  selected independently via `/dev/serial/by-path/...` or `/dev/ttyUSBx`.

## 0.2.0 (candidate)

- Bounded binary/AT parsing and mid-frame receive deadlines.
- Graceful idle connection shutdown, bounded connection and close waits.
- Exclusive serial access, bounded response sizes and no fake success for AT writes.
- Persistent generated PN for new installs; explicit existing PNs retained.
- Pinned callback endpoint by default, validated discovery datagrams.
- Single source layout, automated tests and native image build CI.
- Home Assistant app configuration, translations and publication workflow.
- Supported build targets: amd64 and aarch64; real-device validation pending.

## 0.1.14

- Explicit Home Assistant base image and Python/serial dependencies.

## 0.1.13

- Correct AT+ prefix recognition for binary transaction IDs starting with 0x41.
