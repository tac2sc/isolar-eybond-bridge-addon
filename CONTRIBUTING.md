# Contributing

Install Python 3.12+, then:

```sh
pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
python tools/validate.py
```

The only maintained bridge source is isolar_eybond_usb_bridge/bridge.py.
Use source-derived EyeBond frames; do not invent register maps or acknowledgements.
Tests include fragmented/coalesced TCP, serial forwarding, reconnection and shutdown.
CI builds native amd64 and aarch64 images and imports/runs tests in the image.

Do not use real inverter writes in CI. Test documented settings on hardware only
after verifying the read values. Explain unsupported cases and migration changes.
Human maintainers must review and understand AI-assisted changes before submission
to external projects. This repository does not imply endorsement by Home Assistant.
