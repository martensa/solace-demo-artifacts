# syntax=docker/dockerfile:1
# G0-01 MCP stub (gpos-spike-p01). No GEBIT material in the image.
#   docker build -t gpos-spike-p01-stub:spike .
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
COPY app/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt
WORKDIR /app
COPY app/stub_server.py /app/stub_server.py
COPY tools/measure_sizes.py /app/measure_sizes.py
USER 10001:10001
EXPOSE 8765
ENTRYPOINT ["python", "/app/stub_server.py"]
