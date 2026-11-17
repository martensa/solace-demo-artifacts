"""Start `python -m gebitsim.server` as a subprocess (descriptors via env, like a mounted ConfigMap) and time to SERVING."""
import os, subprocess, sys, time
import grpc
from grpc_health.v1 import health_pb2, health_pb2_grpc
spike, pbs, port = sys.argv[1], sys.argv[2], sys.argv[3]
env = dict(os.environ, GEBIT_DESCRIPTOR_SETS=pbs, PYTHONPATH=spike)
t0 = time.perf_counter()
p = subprocess.Popen([sys.executable, "-m", "gebitsim.server", "--port", port], cwd="/", env=env,
                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
ch = grpc.insecure_channel(f"localhost:{port}")
stub = health_pb2_grpc.HealthStub(ch)
while True:
    try:
        r = stub.Check(health_pb2.HealthCheckRequest(service=""), timeout=0.2)
        if r.status == health_pb2.HealthCheckResponse.SERVING:
            break
    except grpc.RpcError:
        time.sleep(0.02)
    if time.perf_counter() - t0 > 20:
        print("timeout"); break
print(f"process start -> SERVING: {(time.perf_counter() - t0)*1000:.0f} ms")
p.terminate(); out, _ = p.communicate(timeout=5)
print(out.strip().splitlines()[-1][:300] if out.strip() else "(no log)")
