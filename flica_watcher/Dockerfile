FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy

ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN python3 -m pip install --no-cache-dir playwright==1.48.0 paho-mqtt==2.1.0 beautifulsoup4==4.12.3 requests==2.32.3 \
 && python3 -c "import playwright, paho.mqtt, bs4, requests; print('deps ok')"

WORKDIR /app
COPY watcher.py pot.py rules.py store.py web.py /app/

CMD ["python3", "-u", "/app/watcher.py"]
