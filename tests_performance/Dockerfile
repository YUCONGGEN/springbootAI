FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
RUN mkdir -p /tmp/prometheus

COPY requirements-lock.txt ./
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements-lock.txt

COPY spring ./spring
COPY tests_performance ./tests_performance

EXPOSE 8080

CMD ["python", "-m", "uvicorn", "tests_performance.benchmark_app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "2", "--no-access-log"]
