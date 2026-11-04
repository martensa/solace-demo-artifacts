# BSG trading desk demo -- one image, four commands:
#   python -m bsgdemo.publisher      feed-publisher
#   python -m bsgdemo.watcher        feed-watcher   (:8080)
#   python -m bsgdemo.tools_server   bsg-tools MCP  (:8765/mcp)
#   python -m bsgdemo.ui.server      demo-ui        (:8080)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bsgdemo ./bsgdemo
RUN useradd --uid 10001 --create-home bsg && mkdir -p /data && chown bsg /data
USER 10001

EXPOSE 8080 8765
CMD ["python", "-m", "bsgdemo.watcher"]
