FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
RUN pip install ".[postgres,gsheets]"

RUN useradd --create-home app && mkdir -p /app/output && chown -R app /app
USER app

ENTRYPOINT ["pipeline"]
CMD ["list"]
