# Backend image: FastAPI CLI only, port 8100. No direct uvicorn/gunicorn dependency.
# NOTE: `fastapi run` is provided by fastapi-cli (a FastAPI dependency).
# Do not add uvicorn/gunicorn/hypercorn to pyproject.toml.
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir . && \
    pip install --no-cache-dir fastapi-cli

COPY . .

EXPOSE 8100

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8100/health')"

CMD ["fastapi", "run", "main.py", "--port", "8100"]
