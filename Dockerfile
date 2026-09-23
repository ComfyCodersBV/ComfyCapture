FROM mcr.microsoft.com/playwright/python:v1.63.0-noble

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    XDG_DATA_HOME=/data \
    BROWSERTESTS_DATABASE=/data/browsertests.sqlite

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src

RUN pip install --break-system-packages uv \
    && uv export --frozen --no-dev --no-emit-project --no-hashes -o /tmp/requirements.txt \
    && pip install --break-system-packages -r /tmp/requirements.txt \
    && pip install --break-system-packages --no-deps . \
    && rm /tmp/requirements.txt \
    && mkdir -p /data && chown pwuser:pwuser /data

USER pwuser
VOLUME ["/data"]
ENTRYPOINT ["browsertests"]
CMD ["--help"]
