# G0-05 S5 MCP stub. Base = the BSG demo image (python 3.12 + mcp 2.2.0),
# so the build needs no network. Synthetic test images only.
FROM registry.solace.lab/bsg-demo/bsg-demo:0.1.0
COPY --chown=10001 photo_stub.py /app/photo_stub.py
COPY --chown=10001 img/ /app/img/
USER 10001
EXPOSE 8766
CMD ["python", "/app/photo_stub.py"]
