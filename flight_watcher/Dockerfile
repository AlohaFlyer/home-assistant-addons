FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy

ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils && rm -rf /var/lib/apt/lists/*
RUN python3 -m pip install --no-cache-dir playwright==1.48.0 paho-mqtt==2.1.0 beautifulsoup4==4.12.3 requests==2.32.3 cryptography==43.0.3 \
 && python3 -c "import playwright, paho.mqtt, bs4, requests, cryptography; print('deps ok')"

WORKDIR /app
COPY run.py watcher.py pot.py far.py tradeboard.py rules.py store.py web.py swap.py swapmap.py grid.py submit.py inflt.py charter.py versions.py pdfs.py recall.py ccr.py crewidx.py tickets.py cards.py migrate.py sealed.py pay.py seniority.py wwwfiles.py trades.py chunks.py contacts.py working.py /app/
COPY www /app/www

CMD ["python3", "-u", "/app/run.py"]
