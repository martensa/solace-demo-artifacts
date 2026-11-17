""".env.example (spec 12.7) and scripts/check_hygiene.sh (spec 12.6) in a scratch tree."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from conftest import ROOT

from opslib import parse_dotenv

ENV_KEYS = [
    "GPOS_NS", "GPOS_IMAGE", "GPOS_VERSION", "SAM_URL", "SAM_RUN_IDENTITY", "BROKER_SMF_URL",
    "BROKER_WS_URL", "BROKER_VPN", "BROKER_CREDENTIALS_FROM", "SEMP_URL", "SEMP_PASSWORD_FROM",
    "R1_MODE", "R1_QUEUE", "GPOS_DELIVERY", "PG_CONTAINER", "PG_HOST_FROM_PODS", "PG_PORT",
    "PG_DB", "GEBIT_DESCRIPTOR_DIR", "GPOS_DEMO_DATE", "GPOS_BOOTH_LOCATION",
    "GPOS_TEST_LOCATION", "GPOS_PROBE_LOCATION", "GATE_MIN_DELAY_S", "GATE_GUARD",
    "E2E_BASE_URL", "E2E_CA_FILE"]


def test_env_example_has_the_spec_keys_and_no_llm_variable() -> None:
    text = (ROOT / ".env.example").read_text()
    values = parse_dotenv(ROOT / ".env.example", base={"HOME": "/home/x"})
    assert list(values) == ENV_KEYS
    assert values["GEBIT_DESCRIPTOR_DIR"] == "/home/x/Downloads/Gebit"
    assert (values["R1_MODE"], values["GATE_GUARD"]) == ("own", "block")
    assert values["BROKER_SMF_URL"] == "tcp://host.docker.internal:55557"
    assert not any(word in text.upper() for word in ("LLM_SERVICE", "OPENAI", "LITELLM"))


def test_bash_reads_env_example_like_python() -> None:
    proc = subprocess.run(["/bin/bash", "-c", "set -a; . ./.env.example; set +a; env"],
                          cwd=ROOT, capture_output=True, text=True, check=True,
                          env={"HOME": "/home/x", "PATH": os.environ["PATH"]})
    from_bash = dict(line.split("=", 1) for line in proc.stdout.splitlines() if "=" in line)
    parsed = parse_dotenv(ROOT / ".env.example", base={"HOME": "/home/x"})
    assert {k: from_bash[k] for k in parsed} == parsed


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    (tmp_path / "scripts").mkdir()
    shutil.copy(ROOT / "scripts" / "check_hygiene.sh", tmp_path / "scripts")
    (tmp_path / "mesh").mkdir()
    (tmp_path / "mesh" / "ok.yaml").write_text("kind: agent\nname: x\n")
    return tmp_path


def hygiene(tree: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(tree / "scripts" / "check_hygiene.sh")], capture_output=True,
                          text=True, check=False)


def test_clean_tree_passes(tree: Path) -> None:
    assert hygiene(tree).returncode == 0


@pytest.mark.parametrize("rel,content", [
    ("research/purchase-api-2.50.0.pb", "x"),
    ("data/simpleSale.json", "{}"),
    ("proto/vendor/x.proto", 'syntax = "proto3";\npackage de.gebit.rp.purchase;\n'),
    ("mesh/agents/a.yaml", "url: ${LLM_URL}\n"),
    ("mesh/workflows/w.yaml", "tools:\n  - tool_" + "config: {}\n"),
    ("scripts/x.py", "KEY = 'sk-" + "A" * 24 + "'\n"),
    ("app/gposdemo/x.py", "headers = {'api_" + "key': 1}\n"),
    (".env", "LLM_SERVICE_" + "API_KEY=x\n"),
    ("DESIGN.md", "LiteLLM über `lite-" + "llm.example.net`\n"),       # LLM endpoint
    ("mesh/models.yaml", "base: https://Lite" + "LLM.example.org/v1\n"),
])
def test_forbidden_content_fails(tree: Path, rel: str, content: str) -> None:
    target = tree / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    proc = hygiene(tree)
    assert proc.returncode == 1
    assert rel.split("/")[-1] in proc.stderr or rel.split("/")[0] in proc.stderr
    assert "sk-AAAA" not in proc.stderr                    # never echoes the hit itself


def test_proxy_host_check_spares_history_and_prose(tree: Path) -> None:
    """spikes/ and research/ keep their history; prose naming LiteLLM is fine."""
    for rel in ("spikes/g0/x.py", "research/notes.md"):
        (tree / rel).parent.mkdir(parents=True, exist_ok=True)
        (tree / rel).write_text("host = 'lite-" + "llm.example.net'\n")
    (tree / "README.md").write_text("Der LiteLLM-Proxy steht nur in SAM. LiteLLM. Ende.\n")
    assert hygiene(tree).returncode == 0


def test_rendered_files_are_not_scanned(tree: Path) -> None:
    rendered = tree / "mesh" / ".rendered"
    rendered.mkdir()
    (rendered / "x.yaml").write_text("password: ${X}\n")
    assert hygiene(tree).returncode == 0


def test_this_demo_is_clean() -> None:
    proc = subprocess.run([str(ROOT / "scripts" / "check_hygiene.sh")], capture_output=True,
                          text=True, check=False)
    assert proc.returncode == 0, proc.stderr
