# Release and official submission checklist

The requested target repository is
`https://github.com/tac2sc/isolar-eybond-bridge-addon`.

## To publish this community app

1. Owner reviews every code/protocol change, copyright provenance and MPL-2.0
   notice, then creates or grants write access to the target GitHub repository.
2. Push this directory as the repository root.
3. Enable Actions and GHCR package publication. Protect the `release`
   environment with a human reviewer; enable private vulnerability reporting.
4. Run Check workflow. Verify native amd64 and aarch64 image builds.
5. Install locally on real HAOS (first comment out the `image` key in app
   config.yaml, then reload the local store), validate USB mapping, 9600 8N1, discovery/callback, serial
   reads, clean restart and unchanged PN migration. Test write/readback only
   with a safe documented register and owner supervision.
6. Trigger Publish reviewed candidate with tag `0.2.1`. Confirm the GHCR
   package is **public** and contains both amd64 and arm64 manifests.
7. Restore the `image` key in the published source, confirm a fresh HAOS install pulls the image,
   then tag the reviewed source and announce the community repository.
8. Maintain changelog, security reports and dependency updates.

The account has no authenticated GitHub CLI in this workspace and Docker Engine
is unavailable. No push, GHCR release or hardware validation has been claimed.

## Official Home Assistant repository

The community repo above can be submitted to
`home-assistant/addons` for maintainer consideration only after real device
evidence and sustained maintenance. Acceptance is controlled by Home Assistant;
a working custom app does not become official automatically. The Home Assistant
project's AI policy requires the human submitter to understand and explain
AI-assisted changes. If maintainers favor a community repository, retain this
install path instead of claiming official status.

Potential review concerns: host networking and broad `uart: true` mapping
(required by current broadcast discovery and selectable serial hardware),
unauthenticated EyeBond traffic, and dependency on a custom integration.
Explain the compatibility reason and practical network boundary in the PR.
