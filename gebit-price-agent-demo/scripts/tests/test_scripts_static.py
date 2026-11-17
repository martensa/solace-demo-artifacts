"""Static guarantees of scripts/ and the Makefile (spec 9.8, 11.7, 12.5, 12.6)."""

from __future__ import annotations

import py_compile
import re
import subprocess
from pathlib import Path

import pytest
from conftest import ROOT

SCRIPTS = ROOT / "scripts"
SHELL = sorted(SCRIPTS.glob("*.sh"))
PYTHON = sorted(SCRIPTS.glob("*.py"))


def code_lines(path: Path) -> list[str]:
    return [ln for ln in path.read_text().splitlines() if not ln.lstrip().startswith("#")]


@pytest.mark.parametrize("path", SHELL, ids=lambda p: p.name)
def test_shell_syntax(path: Path) -> None:
    subprocess.run(["/bin/bash", "-n", str(path)], check=True)
    assert path.stat().st_mode & 0o111


@pytest.mark.parametrize("path", PYTHON, ids=lambda p: p.name)
def test_python_compiles(path: Path, tmp_path: Path) -> None:
    py_compile.compile(str(path), cfile=str(tmp_path / "x.pyc"), doraise=True)


def test_spec_script_set_is_complete() -> None:
    names = {p.name for p in SHELL + PYTHON}
    assert {"lib.sh", "install.sh", "uninstall.sh", "reset.sh", "broker.sh", "render_mesh.py",
            "gen_connector_manifest.py", "check_manifests.py", "sam_inbox.py", "smoke.sh",
            "smoke.py", "e2e.sh", "e2e.py", "check_hygiene.sh", "port_forward.sh"} <= names


APPLY_CALL = re.compile(r'SAM_CLI"?\s+config\s+apply|"config",\s*"apply"')
TOKEN_USE = re.compile(r"\$\{?SAM_AUTH_TOKEN|environ\b.*SAM_AUTH_TOKEN")


def test_config_apply_only_through_the_guarded_helper() -> None:
    callers = {p.name for p in SHELL + PYTHON
               if any(APPLY_CALL.search(line) for line in code_lines(p))}
    assert callers == {"lib.sh"}
    lib = (SCRIPTS / "lib.sh").read_text()
    assert '"--prune"' not in lib and "forbidden (hard rule 3)" in lib
    assert "config apply --no-dotenv --no-interactive" in lib


def test_token_never_on_a_command_line() -> None:
    users = [p.name for p in SHELL + PYTHON
             if any(TOKEN_USE.search(line) for line in code_lines(p))]
    assert users == ["lib.sh"]
    assert "--config -" in (SCRIPTS / "lib.sh").read_text()        # curl reads it from stdin


def test_install_mesh_follows_9_8() -> None:
    text = (SCRIPTS / "install.sh").read_text()
    body = text[text.index("install_mesh() {"):]
    steps = [f'"4.{n} ' for n in range(1, 11)]
    positions = [body.index(s) for s in steps]
    assert positions == sorted(positions)
    assert body.index("gate_verify_if_needed") < body.index("manifest-booth.yaml")
    # --no-booth stops right after the gate verification, before R1 queue and booth
    stop = body.index('if [ -n "$NO_BOOTH" ]; then')
    assert body.index("gate_verify_if_needed\n") < stop < body.index('"4.8 ')
    assert "return 0" in body[stop:body.index('"4.8 ')]
    assert body.index("manifest-probe.yaml") < body.index("gate_verify_if_needed")
    assert body.index("check_manifests.py") < body.index("sam_apply")
    assert 'hygiene_or_die\ncase "$PART" in' in text      # refuses to start when unclean


def test_reset_cancels_requests_after_the_chain() -> None:
    text = "\n".join(code_lines(SCRIPTS / "reset.sh"))
    assert text.index("ui_ctl reset") < text.index("cancel-gpos") < text.index("orphans")


def test_uninstall_order() -> None:
    text = "\n".join(code_lines(SCRIPTS / "uninstall.sh"))
    kinds = [text.index(f"delete_named {k}") for k in ("entrypoint", "workflow", "agent",
                                                       "connector")]
    assert kinds == sorted(kinds)
    assert text.index("r1-delete") < text.index("delete ns")


def test_makefile_has_the_spec_targets() -> None:
    targets = set(re.findall(r"^([a-z0-9-]+):", (ROOT / "Makefile").read_text(), re.M))
    assert {"help", "venv", "protos", "test", "test-db", "test-gebit", "test-int", "hygiene",
            "build", "push", "db-up", "k8s-up", "manifests", "mesh-up", "demo-up", "demo-reset",
            "demo-watch", "smoke", "gate-verify", "e2e", "port-forward", "status", "logs",
            "urls", "uninstall"} <= targets
    demo_up = re.search(r"^demo-up: (.*?)  ##", (ROOT / "Makefile").read_text(), re.M).group(1)
    assert demo_up.split() == ["hygiene", "db-up", "k8s-up", "mesh-up", "smoke", "urls"]
