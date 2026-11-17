# syntax=docker/dockerfile:1
# G0-07 spike image: gebitsim gRPC server (spikes/grpc-spike/gebitsim) plus a
# tiny HTTP upload sink for the body-size test. NO GEBIT material in the
# image: the descriptor sets are mounted at runtime (Secret in ns gpos-g0).
#
# Build (from spikes/g0/g0-07, see build.sh):
#   docker buildx build --load -t gpos-g0-grpc:spike \
#     --build-context gebitsim=../../grpc-spike/gebitsim .
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

WORKDIR /app
COPY --from=gebitsim *.py /app/gebitsim/
COPY upload_sink.py /app/upload_sink.py

USER 10001:10001
EXPOSE 50051 8080

# Descriptor paths come from GEBIT_DESCRIPTOR_SETS (set in the Deployment).
ENTRYPOINT ["python", "-m", "gebitsim.server"]
CMD ["--port", "50051"]
