ARG BUILD_FROM
FROM ${BUILD_FROM}

# Install Python and dependencies
RUN apk add --no-cache python3 py3-pip py3-aiohttp

# Install Python packages
RUN pip3 install --no-cache-dir --break-system-packages \
    aiohttp \
    anthropic \
    pyyaml

# Copy application
WORKDIR /app
COPY run.sh /
COPY src/ /app/

RUN chmod a+x /run.sh

CMD ["/run.sh"]
