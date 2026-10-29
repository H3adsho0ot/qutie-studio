FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    QUTIE_DATA=/data \
    QUTIE_TRANSPORT=usb

LABEL org.opencontainers.image.title="Qutie Studio" \
    org.opencontainers.image.description="Local label designer and print server for HPRT Qutie/Q2" \
    org.opencontainers.image.source="https://github.com/H3adsho0ot/qutie-studio" \
    org.opencontainers.image.documentation="https://github.com/H3adsho0ot/qutie-studio#docker"

RUN apt-get update \
    && apt-get install --no-install-recommends -y liblzo2-2 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 qutie \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin qutie \
    && install -d -o 10001 -g 10001 /data

WORKDIR /app
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY app.py printer.py README.md THIRD_PARTY_NOTICES.md ./
COPY static/ ./static/
COPY vendor/qutie-linux/LICENSE ./vendor/qutie-linux/LICENSE
COPY vendor/qutie-linux/src/ ./vendor/qutie-linux/src/

# Check both target architectures during the build, without touching hardware.
RUN python -c "import socket, printer, fastapi, uvicorn, PIL.Image, qrcode; from qutie import lzo; assert hasattr(socket, 'AF_BLUETOOTH') and hasattr(socket, 'BTPROTO_RFCOMM'); assert lzo._load() is not None"

USER 10001:10001
VOLUME ["/data"]
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/', timeout=3).close()"]

CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8765", "--workers", "1"]
