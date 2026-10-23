FROM python:3.13-slim-bookworm
ARG APP_UID=1002
ARG APP_GID=1002
ARG APP_HOME=/home/alex
ARG REVISION=development
RUN apt-get update && apt-get install -y --no-install-recommends openssh-client git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN groupadd --gid "$APP_GID" developer && useradd --uid "$APP_UID" --gid "$APP_GID" \
    --home-dir "$APP_HOME" --create-home developer
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN pip install --no-cache-dir uv==0.10.9 && uv sync --frozen --no-dev --no-editable
COPY scripts/codex_host.sh /usr/local/bin/codex-host
RUN chmod 755 /usr/local/bin/codex-host
ENV VIBECODING_CORE_REVISION=$REVISION
ENV PATH="/app/.venv/bin:$PATH"
USER developer
ENTRYPOINT ["/bin/sh", "-c", "umask 077; exec /app/.venv/bin/vibecoding-core \"$@\"", "--"]
CMD ["serve"]
