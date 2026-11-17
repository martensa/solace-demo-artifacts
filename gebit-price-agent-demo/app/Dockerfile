# syntax=docker/dockerfile:1
# gpos-demo: one image, six commands (pos, wws, loyalty, engine, gate, ui).
# NO GEBIT material: purchase/receipt descriptor sets are mounted at runtime.
# Build from the demo root:  docker build -f app/Dockerfile -t <image> .
FROM python:3.13-slim AS protos
RUN pip install --no-cache-dir grpcio-tools==1.85.1
COPY proto /src/proto
RUN mkdir -p /out && cd /src/proto && python -m grpc_tools.protoc -I . \
      --include_imports --descriptor_set_out=/out/showcase.pb \
      $(find de -name '*.proto' | sort)

FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    SHOWCASE_DESCRIPTOR_SET=/app/descriptors/showcase.pb \
    POLICY_FILE=/app/policy/pricing-policy.yaml DATA_DIR=/app/data
WORKDIR /app
COPY app/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt
COPY --from=protos /out/showcase.pb /app/descriptors/showcase.pb
COPY app/gposdemo /app/gposdemo
COPY data /app/data
COPY policy /app/policy
USER 10001:10001
EXPOSE 8090 8765 8766 8771 8772 8773 50051 50052 50053
CMD ["python", "-m", "gposdemo.ui"]
