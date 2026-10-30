FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy

RUN pip install --no-cache-dir paho-mqtt==2.1.0 beautifulsoup4==4.12.3 requests==2.32.3

WORKDIR /app
COPY watcher.py /app/watcher.py

CMD ["python3", "-u", "/app/watcher.py"]
