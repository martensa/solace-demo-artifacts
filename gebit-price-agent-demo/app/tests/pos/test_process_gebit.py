"""``python -m gposdemo.pos`` as a real process (markers db, gebit; 2.3, 8.1, 11.8).

Starts the command with ``GPOS_BUS=memory`` against the scratch DB and the stub
WWS/loyalty servers, then talks to it like the cluster does: HTTP ``/health``,
``/admin/till/{till}``, ``/admin/reset``, MCP ``tools/list`` on ``/mcp`` and gRPC on
its port; SIGTERM must end it cleanly.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from google.protobuf import descriptor_pool

from gposdemo.common import grpcutil
from gposdemo.common.config import Settings
from gposdemo.common.descriptors import PURCHASE_SVC

from .conftest import Stub

pytestmark = [pytest.mark.db, pytest.mark.gebit]

APP_DIR = Path(__file__).resolve().parents[2]
HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def pos_process(scratch_db: Any, settings: Settings, wws_stub: Stub, loyalty_stub: Stub,
                tmp_path: Path) -> Iterator[tuple[subprocess.Popen[str], int, int]]:
    grpc_port, http_port = free_port(), free_port()
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path),
           "PYTHONPATH": str(APP_DIR), "GPOS_BUS": "memory", "GPOS_DSN": scratch_db.dsn("pos"),
           "GPOS_DEMO_DATE": "2027-02-16", "GPOS_TOOL_STORE": "199",
           "GEBIT_DESCRIPTOR_SETS": os.pathsep.join(settings.gebit_descriptor_sets),
           "SHOWCASE_DESCRIPTOR_SET": settings.showcase_descriptor_set,
           "GRPC_PORT": str(grpc_port), "MCP_PORT": str(http_port),
           "WWS_GRPC": wws_stub.target, "LOYALTY_GRPC": loyalty_stub.target,
           "LOG_LEVEL": "WARNING"}
    proc = subprocess.Popen([sys.executable, "-m", "gposdemo.pos"], env=env, cwd=tmp_path,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        yield proc, grpc_port, http_port
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait(10)


def wait_healthy(base: str, proc: subprocess.Popen[str], timeout: float = 30.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            output = proc.stdout.read() if proc.stdout else ""
            pytest.fail(f"gpos-pos exited with {proc.returncode}: {output}")
        try:
            reply = httpx.get(f"{base}/health", timeout=1.0)
            if reply.status_code == 200:
                return reply.json()
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    pytest.fail("gpos-pos did not become healthy")


def test_process_serves_health_admin_mcp_and_grpc(
        pos_process: tuple[subprocess.Popen[str], int, int],
        gebit_pool: descriptor_pool.DescriptorPool) -> None:
    proc, grpc_port, http_port = pos_process
    base = f"http://127.0.0.1:{http_port}"
    assert wait_healthy(base, proc) == {"status": "ok", "db": True, "bus": True}

    client = grpcutil.Client(gebit_pool, PURCHASE_SVC, f"127.0.0.1:{grpc_port}")
    try:
        tx = client.call("CreatePurchaseTransaction", {
            "header": {"traceId": "kasse-99-proc"}, "location": "Root.DE.999.199.99",
            "employeeId": "booth", "cashdrawerId": "99"}).purchase_transaction_id
    finally:
        client.close()
    till = httpx.get(f"{base}/admin/till/99", timeout=5).json()
    assert (till["till"], till["store"], till["open_tx"]["tx_id"]) == ("99", "199", tx)
    assert httpx.get(f"{base}/admin/till/07", timeout=5).status_code == 404
    assert httpx.post(f"{base}/admin/reset", timeout=5).json()["reset"] >= 1
    assert httpx.get(f"{base}/admin/till/99", timeout=5).json()["open_tx"] is None

    listed = httpx.post(f"{base}/mcp", headers=HEADERS, timeout=5, json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}).json()
    assert [t["name"] for t in listed["result"]["tools"]] == ["get_transaction",
                                                               "get_till_status"]
    status = httpx.post(f"{base}/mcp", headers=HEADERS, timeout=5, json={
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "get_till_status", "arguments": {"ref": "GR-1"}}}).json()
    assert '"till":"99"' in status["result"]["content"][0]["text"]

    proc.send_signal(signal.SIGTERM)
    assert proc.wait(15) == 0
