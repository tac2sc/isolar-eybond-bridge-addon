"""Check publication metadata and source against the Home Assistant app contract."""

from __future__ import annotations

from pathlib import Path
import re

import yaml


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "isolar_eybond_usb_bridge"
config = yaml.safe_load((APP / "config.yaml").read_text(encoding="utf-8"))
repo = yaml.safe_load((ROOT / "repository.yaml").read_text(encoding="utf-8"))
assert config["slug"] == APP.name
assert re.fullmatch(r"\d+\.\d+\.\d+", config["version"])
assert set(config["arch"]) == {"aarch64", "amd64"}
assert config["image"] == "ghcr.io/tac2sc/isolar-eybond-bridge-addon"
assert config["host_network"] is True
assert config["uart"] is True
assert config["schema"]["serial_device"] == "str"
assert config["options"]["allow_remote_redirect"] is False
assert repo["name"] and repo["url"].startswith("https://github.com/")
dockerfile = (APP / "Dockerfile").read_text(encoding="utf-8")
assert "FROM ghcr.io/home-assistant/base:" in dockerfile
assert "BUILD_FROM" not in dockerfile
assert "python3 py3-pyserial" in dockerfile
assert "io.hass.arch" in dockerfile
for name in ("README.md", "DOCS.md", "CHANGELOG.md", "LICENSE", "NOTICE", "run.sh", "bridge.py"):
    assert (APP / name).is_file(), name
assert (ROOT / "LICENSE").is_file()
for lang in ("en", "ru"):
    translation = yaml.safe_load(
        (APP / "translations" / f"{lang}.yaml").read_text(encoding="utf-8")
    )
    assert set(config["schema"]) <= set(translation["configuration"])
print("Home Assistant publication metadata OK")
