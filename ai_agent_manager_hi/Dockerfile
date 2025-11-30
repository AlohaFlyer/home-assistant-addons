ARG BUILD_FROM
FROM ${BUILD_FROM}

# Install Python and dependencies
RUN apk add --no-cache \
    python3 \
    py3-pip \
    py3-aiohttp \
    py3-yaml \
    && pip3 install --no-cache-dir --break-system-packages \
    anthropic \
    aiohttp \
    websockets \
    python-dateutil \
    apscheduler

# Copy application files
COPY run.sh /
COPY agent_manager/ /agent_manager/

RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
