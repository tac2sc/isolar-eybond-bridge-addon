FROM ghcr.io/home-assistant/base:latest
ARG BUILD_VERSION=0.2.1
ARG BUILD_ARCH
LABEL io.hass.version="${BUILD_VERSION}" \
      io.hass.type="app" \
      io.hass.arch="${BUILD_ARCH}" \
      org.opencontainers.image.title="iSolar EyeBond USB Bridge" \
      org.opencontainers.image.source="https://github.com/tac2sc/isolar-eybond-bridge-addon" \
      org.opencontainers.image.licenses="MPL-2.0"
WORKDIR /app
RUN apk add --no-cache python3 py3-pyserial
COPY bridge.py run.sh LICENSE NOTICE ./
RUN chmod 0755 /app/run.sh \
    && python3 -c "import serial; import bridge"
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
CMD ["/app/run.sh"]
