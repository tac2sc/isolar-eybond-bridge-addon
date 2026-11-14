# iSolar EyeBond USB Bridge 0.2.1 - draft release notes

**Status: release candidate, not a publication notice.**

## Purpose

Home Assistant community app for connecting supported USB serial inverters to the separately installed EyeBond Local integration without a Wi-Fi collector. It emulates the collector protocol and forwards serial traffic; device-specific Modbus decoding and write authorization remain in EyeBond Local.

## Included in candidate

- Collector discovery/callback and FC1 heartbeat lifecycle, FC3 restart/apply acknowledgement/reconnect, serial baud changes and framing robustness.
- HAOS app packaging and documented USB serial selection.
- Automated tests and native amd64/aarch64 container build validation as reported in the project README.

## Compatibility and limitations

- EASUN iSolar SMX-II 3.6 kW / 24 V can use the exact `srne_modbus/smx_ii_24v.json` telemetry schema added in EyeBond Local PR #91 (merged November 14, 2026), subject to installing a compatible integration build.
- Write capabilities described in EyeBond Local PR #96 are **not part of this Bridge release**. PR #96 was open at preparation time. Two capabilities had been physically verified on the owner's unit, not all 36, and an end-to-end write test specifically over USB Bridge remains to be documented.
- CI uses simulated serial responses; broad hardware compatibility and safe operation of unverified writes are not claimed.
- Unauthenticated network protocol: use only a trusted LAN; do not forward UDP 58899 or the callback listener to the Internet.

## Release acceptance gates (must be recorded before publication)

- [ ] Record reviewed source commit and clean test results.
- [ ] Validate app configuration, shell syntax, Python 3.12/3.13 checks, and native amd64/aarch64 image builds.
- [ ] Verify real HAOS app start/stop, stable USB mapping and collector identity after restart.
- [ ] Confirm live exact-model telemetry via USB Bridge and preserve redacted evidence.
- [ ] Document controlled readback/restore testing separately; do not imply it happened through USB if evidence is from a Wi-Fi collector.
- [ ] Publish GHCR amd64 and arm64 images using the reviewed release workflow; confirm public package and manifests.
- [ ] Verify a fresh HAOS install actually pulls the published image.
- [ ] Tag and announce only the source revision that corresponds to the tested image.

See `RELEASE.md`, `HARDWARE_TEST.md` and `docs/SMX_II_24V_INTEROP.md`.
