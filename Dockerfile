FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
COPY config ./config

EXPOSE 8000
CMD ["websensors-flow-rag-api", "--config", "config/rag.yaml"]
