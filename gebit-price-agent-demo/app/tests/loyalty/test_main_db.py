"""``python -m gposdemo.loyalty`` as a process (2.4 ``run()``): gRPC, MCP and /health."""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from google.protobuf import descriptor_pool

from gposdemo.common import grpcutil
from gposdemo.common.descriptors import LOYALTY_SVC
from gposdemo.common.protoc import ensure_local

pytestmark = pytest.mark.db

APP_DIR = Path(__file__).resolve().parents[2]
START_TIMEOUT_S = 30.0


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for(check: Callable[[], bool], proc: subprocess.Popen[bytes], log: Path) -> None:
    deadline = time.monotonic() + START_TIMEOUT_S
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise AssertionError(f"gpos-loyalty exited with {proc.returncode}:\n"
                                 f"{log.read_text(errors='replace')[-2000:]}")
        try:
            if check():
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    raise AssertionError("gpos-loyalty did not become healthy")


@pytest.fixture
def process(scratch_db: Any, tmp_path: Path
            ) -> Iterator[tuple[subprocess.Popen[bytes], int, int]]:
    """The command of the container (``python -m gposdemo.loyalty``) on free ports."""
    grpc_port, mcp_port = _free_port(), _free_port()
    env = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", ""),
           "GPOS_DSN": scratch_db.dsn("loyalty"), "GPOS_BUS": "memory",
           "GPOS_DEMO_DATE": "2027-02-16", "GRPC_PORT": str(grpc_port),
           "MCP_PORT": str(mcp_port), "SHOWCASE_DESCRIPTOR_SET": str(ensure_local()),
           "LOG_LEVEL": "WARNING"}
    log = tmp_path / "loyalty.log"
    with log.open("wb") as sink:
        proc = subprocess.Popen([sys.executable, "-m", "gposdemo.loyalty"], cwd=APP_DIR,
                                env=env, stdout=sink, stderr=subprocess.STDOUT)
    try:
        _wait_for(lambda: httpx.get(f"http://127.0.0.1:{mcp_port}/health",
                                    timeout=2).status_code == 200, proc, log)
        yield proc, grpc_port, mcp_port
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def test_process_serves_grpc_mcp_and_health(
        process: tuple[subprocess.Popen[bytes], int, int],
        showcase_pool: descriptor_pool.DescriptorPool) -> None:
    proc, grpc_port, mcp_port = process
    health = httpx.get(f"http://127.0.0.1:{mcp_port}/health", timeout=5)
    assert health.json() == {"status": "ok", "db": True, "bus": True}
    client = grpcutil.Client(showcase_pool, LOYALTY_SVC, f"127.0.0.1:{grpc_port}")
    try:
        msg = client.call("GetPurchaseBehaviour", {"membership_id": "M-1001",
                                                   "article_number": "100012"})
    finally:
        client.close()
    assert (msg.member_purchases_8w, msg.days_since_last, msg.median_interval_days) == (2, 35, 14)
    reply = httpx.post(f"http://127.0.0.1:{mcp_port}/mcp", timeout=5, headers={
        "Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    names = [t["name"] for t in reply.json()["result"]["tools"]]
    assert names == ["get_member_profile", "get_purchase_behaviour"]
    proc.send_signal(signal.SIGTERM)  # pod stop: MCP ends, gRPC, bus and DB close
    assert proc.wait(timeout=15) == 0
