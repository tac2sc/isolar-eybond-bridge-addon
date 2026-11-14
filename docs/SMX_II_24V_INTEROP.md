# EASUN iSolar SMX-II 24 V: USB Bridge compatibility

## Components and responsibility

- USB Bridge repository: https://github.com/tac2sc/isolar-eybond-bridge-addon
- Integration: https://github.com/groove-max/ha-eybond-local
- Inverter: EASUN iSolar SMX-II 3.6 kW / 24 V, product-info `SR-2206260036-300917`.

The Bridge exposes the serial-connected inverter as an EyeBond-compatible network collector. EyeBond Local identifies the inverter, decodes its Modbus registers and applies model-specific policies. The Bridge must **not** duplicate the SRNE register map or authorize settings on its own.

Path: inverter USB/CH340 serial -> Linux/HAOS USB Bridge -> EyeBond collector framing -> Home Assistant EyeBond Local. Discovery uses UDP 58899; the Bridge establishes the reverse TCP connection to the configured EyeBond Local listener (typically 8899). USB baud is initially 9600 8N1 for the tested SMX-II; serial speed can be negotiated by the collector protocol.

## Integration compatibility

- EyeBond Local upstream PR #91 (merged 2026-11-14): exact `srne_modbus/smx_ii_24v.json` telemetry and exclusions for unsupported registers. Do not use the generic SRNE schema as equivalent evidence.
- EyeBond Local PR #96 (open as of 2026-11-14): 36 exact-model-gated legacy controls. The PR reports physical write/readback tests for `output_priority` and `charger_source_priority` using the owner's inverter. Other settings have not been individually hardware-qualified.
- A working USB Bridge does **not** establish that a particular settings write is safe, nor that the integration PR has been merged or released.

## Evidence required before marking end-to-end telemetry verified

1. Record the Bridge version, installed EyeBond Local commit/version, `srne_modbus/smx_ii_24v.json` selection and inverter identity. Mask serial numbers and collector PN in public reports.
2. Confirm a fresh Bridge callback, accepted PN/collector identity, and live `srne_modbus` telemetry in the same HA session.
3. Obtain an EyeBond Local Support Archive and inspect the read results. Confirm fresh Battery Voltage, Grid Voltage, Output Voltage/Power and Load Percent, with no repeat of the previously unsupported 554-567 register block.
4. Compare at least two displayed readings with the inverter display, with units and timestamps. An entity merely existing or retaining an old state is not sufficient.
5. State explicitly whether the test used **USB Bridge** or the **stock Wi-Fi collector**. These are separate hardware evidence paths.

## Controlled writes are a separate qualification

Use the repository's existing `HARDWARE_TEST.md` and `tools/hardware_controls.py`. The USB path requires temporarily stopping the Bridge app and disabling the integration entry while redirecting the Bridge callback to a local test listener. Keep a record of original endpoint settings and restore them after the run. No unattended writes and no automatic fallback to a different identity/profile.

Start with the read-only inventory. Every subsequent write must have owner approval for the exact control and candidate value, and must verify the original register value before/after the test, the write response, the new readback, the restoration and fresh telemetry after restoring HA connectivity. Failure to restore is a critical failure, not a test pass.

Do not run real inverter writes in CI or while a vital load depends on the inverter. See `HARDWARE_TEST.md` for the runner's excluded controls and safety rules.

## Release 0.2.1 gate

Automated CI and Docker architecture checks are not proof of a successful HAOS store installation or live USB write path. Before publishing 0.2.1, complete the release checklist in `RELEASE.md`, confirm the published GHCR multi-architecture manifest, and perform a fresh HAOS installation/pull test. Publishing the integration and publishing the Bridge are independent decisions.

References: https://github.com/groove-max/ha-eybond-local/pull/91 ; https://github.com/groove-max/ha-eybond-local/pull/96 ; `HARDWARE_TEST.md` ; `RELEASE.md`.
