# Acme Claims Knowledge -- MCP server + seed job image.
# One image, two commands (see ../docker-compose.yaml):
#   python server.py   MCP streamable-http on :8765/mcp + GET /health
#   python seed.py     embeds /app/seed/documents.yaml into Qdrant
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # fastembed model cache (compose mounts the named volume here)
    FASTEMBED_CACHE_DIR=/app/models

WORKDIR /app

# Dependencies first (layer cache): mcp SDK, qdrant client,
# fastembed (ONNX runtime, no torch), pyyaml.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py seed.py ./
RUN mkdir -p /app/models /app/seed

EXPOSE 8765

CMD ["python", "server.py"]
