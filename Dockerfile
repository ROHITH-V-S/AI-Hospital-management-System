# One image for the loader and the app.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements-docker.txt .
RUN pip install -r requirements-docker.txt

COPY pyproject.toml README.md alembic.ini ./
COPY mahros ./mahros
COPY migrations ./migrations
COPY experiments ./experiments
COPY results ./results
COPY tests ./tests
RUN pip install --no-deps -e .

# data/ is mounted from the host so the downloaded cache is shared and kept.
EXPOSE 8000
CMD ["uvicorn", "mahros.server.app:app", "--host", "0.0.0.0", "--port", "8000"]
