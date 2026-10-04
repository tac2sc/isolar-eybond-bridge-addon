# Proposal for Home Assistant maintainers (human review required)

This candidate provides a USB serial adapter to the EyeBond Local custom
integration through the documented reverse EyeBond collector protocol.
The concrete target is an EASUN iSolar SMX II with SRNE Modbus RTU at 9600
8N1. The bridge does not decode inverter registers. FC4 forwards the raw
serial request and, when the inverter responds, the raw reply.

Why an app: HAOS does not run arbitrary host Python daemons. A supervised
app can own the USB adapter and reconnect to the integration over local TCP.
The required permissions are host networking for UDP broadcast discovery and
UART device mapping. No privileged mode or Supervisor API is used.

Before considering inclusion in the official apps repository, a human
maintainer should verify a real HAOS install and the separately maintained
integration, especially callback discovery, identity persistence after
restart, and controlled register writes. The external integration dependency,
host networking, narrow supported hardware and maintenance ownership are
substantive review questions. Official inclusion is not assured.

The owner should write any upstream discussion or PR in their own words
after reviewing the code and evidence. See the Open Home Foundation AI policy:
https://developers.home-assistant.io/docs/ai_policy
