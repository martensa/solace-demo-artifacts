"""Helm chart render tests (Wave 5 / #15).

Shell out to `helm lint` + `helm template` and assert the mode-gated
invariants that matter for a safe deploy. Skipped when `helm` is not on
PATH (e.g. the Docker ingestion test image)."""
import shutil
import subprocess
from pathlib import Path

import pytest

if shutil.which("helm") is None:
    pytest.skip("helm not installed", allow_module_level=True)

CHART = str(Path(__file__).resolve().parents[1] / "charts" / "solace-eventportal-bridge")
SECRET = ["--set", "secret.epApiToken=ep", "--set", "secret.omJwtToken=om"]
EXISTING = ["--set", "secret.existingSecret=mine"]


def _template(*extra):
    out = subprocess.run(
        ["helm", "template", "r", CHART, *extra],
        capture_output=True, text=True,
    )
    assert out.returncode == 0, out.stderr
    return out.stdout


def test_helm_lint_passes():
    out = subprocess.run(
        ["helm", "lint", CHART, *EXISTING], capture_output=True, text=True
    )
    assert out.returncode == 0, out.stdout + out.stderr


def test_polling_default_has_no_probes_or_service():
    # Polling has no HTTP server; naive probes would crashloop the pod.
    rendered = _template(*SECRET)
    assert "Probe:" not in rendered
    assert "kind: Service" not in rendered


def test_metrics_enabled_renders_service_and_tcp_probe():
    rendered = _template(*SECRET, "--set", "observability.metrics.enabled=true")
    assert "kind: Service" in rendered
    assert "tcpSocket:" in rendered
    assert "prometheus.io/scrape" in rendered


def test_http_mode_renders_httpget_probes():
    rendered = _template(*SECRET, "--set", "mode=http")
    assert "httpGet:" in rendered
    assert "/readyz" in rendered
    assert "name: webhook" in rendered


def test_solace_mode_injects_solace_env():
    rendered = _template(*SECRET, "--set", "mode=solace")
    assert "BRIDGE_SOLACE_HOST" in rendered
    assert "BRIDGE_SOLACE_PASSWORD" in rendered


def test_otel_collector_sidecar_and_endpoint():
    rendered = _template(*EXISTING, "--set", "otelCollector.enabled=true")
    assert "name: otel-collector" in rendered
    assert "http://localhost:4318" in rendered
    assert "kind: ConfigMap" in rendered
    assert 'BRIDGE_OBS_OTEL_ENABLED\n              value: "true"' in rendered


def test_cronjobs_render_with_correct_args():
    rendered = _template(
        *EXISTING,
        "--set", "cron.softDelete.enabled=true",
        "--set", "cron.reconcile.enabled=true",
    )
    assert rendered.count("kind: CronJob") == 2
    assert "--soft-delete-missing" in rendered
    assert "--reconcile" in rendered


def test_existing_secret_renders_no_chart_secret():
    rendered = _template(*EXISTING)
    assert "kind: Secret" not in rendered


def test_missing_secret_without_existing_fails_render():
    # Must refuse to render an empty/broken Secret.
    out = subprocess.run(
        ["helm", "template", "r", CHART], capture_output=True, text=True
    )
    assert out.returncode != 0
    assert "epApiToken is required" in out.stderr


def test_lab_ca_trust_mounts_bundle_and_env():
    rendered = _template(*EXISTING, "--set", "labCaTrust.enabled=true")
    assert "REQUESTS_CA_BUNDLE" in rendered
    assert "name: lab-ca" in rendered
