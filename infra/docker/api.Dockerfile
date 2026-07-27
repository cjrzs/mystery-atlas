FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY workers/analyzer ./workers/analyzer
COPY apps/api ./apps/api

RUN python -m pip install --no-cache-dir ./workers/analyzer ./apps/api

WORKDIR /app/apps/api

EXPOSE 8010

CMD ["python", "-m", "uvicorn", "mystery_atlas_api.main:app", "--host", "0.0.0.0", "--port", "8010"]
