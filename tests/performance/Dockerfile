FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10 \
    LANGGRAPH_STRICT_MSGPACK=true

WORKDIR /app
RUN mkdir -p /tmp/prometheus

COPY requirements-lock.txt ./
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements-lock.txt

# Keep optional groups in separate cache layers. A temporary PyPI/network
# failure in the last group should not reinstall the whole core environment.
COPY requirements-ai.txt ./
RUN python -m pip install -r requirements-ai.txt

COPY requirements-langgraph.txt ./
RUN python -m pip install -r requirements-langgraph.txt

COPY requirements-mcp.txt ./
RUN python -m pip install -r requirements-mcp.txt

COPY spring ./spring
COPY tests/performance ./tests/performance

EXPOSE 8080

CMD ["python", "-m", "uvicorn", "tests.performance.benchmark_app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "2", "--no-access-log"]
