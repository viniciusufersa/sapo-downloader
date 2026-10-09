FROM node:24-bookworm-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend \
    FRONTEND_DIST=/app/frontend/dist \
    TEMP_DIR=/tmp/sapo-downloads \
    PORT=10000
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system app \
    && useradd --system --gid app --home-dir /app app \
    && mkdir -p /app/frontend /app/backend /tmp/sapo-downloads \
    && chown -R app:app /app /tmp/sapo-downloads
COPY --from=frontend-build /usr/local/bin/node /usr/local/bin/node
COPY backend/requirements.lock /app/backend/requirements.lock
RUN pip install --no-cache-dir --require-hashes -r /app/backend/requirements.lock
COPY backend/app /app/backend/app
COPY backend/run.py /app/backend/run.py
COPY --from=frontend-build /app/frontend/dist /app/frontend/dist
WORKDIR /app
USER app
EXPOSE 10000
CMD ["python", "/app/backend/run.py"]
