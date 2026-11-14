# Proposal for Home Assistant maintainers

This candidate provides a USB serial adapter to the EyeBond Local custom
integration through the documented reverse EyeBond collector protocol.
The concrete target is an EASUN iSolar SMX II with SRNE Modbus RTU at 9600
8N1. The bridge does not decode inverter registers. FC4 forwards the raw
serial request and, when the inverter responds, the raw reply.

Why an app: HAOS does not run arbitrary host Python daemons. A supervised
app can own the USB adapter and reconnect to the integration over local TCP.
The required permissions are host networking for UDP broadcast discovery and
UART device mapping. No privileged mode or Supervisor API is used.
