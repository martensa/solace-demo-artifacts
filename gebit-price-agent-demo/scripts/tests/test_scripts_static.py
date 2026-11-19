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


APPLY_CALL = re.compile(r'(SAM_CLI"?|\bsam_cli)\s+config\s+apply|"config",\s*"apply"')
TOKEN_USE = re.compile(r"\$\{?SAM_AUTH_TOKEN|environ\b.*SAM_AUTH_TOKEN")


def test_config_apply_only_through_the_guarded_helper() -> None:
    callers = {p.name for p in SHELL + PYTHON
               if any(APPLY_CALL.search(line) for line in code_lines(p))}
    assert callers == {"lib.sh"}
    lib = (SCRIPTS / "lib.sh").read_text()
    assert '"--prune"' not in lib and "forbidden (hard rule 3)" in lib
    assert "sam_cli config apply --no-dotenv --no-interactive" in lib
    # aks: the CLI with HOME=$SAM_HOME (its own login cache), never a token of the shell
    assert 'env -u SAM_AUTH_TOKEN -u SAM_PLATFORM_TOKEN HOME="$SAM_HOME" "$SAM_CLI"' in lib


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


# ------------------------------------------------------- TARGET=lab|aks (AKS 1.4)
# Stubbed runs: test_target_shell.py. Here: the static shape of the switch.


def test_lib_switches_env_file_by_target() -> None:
    text = (SCRIPTS / "lib.sh").read_text()
    lab = text[text.index("  lab)\n"):text.index("  aks)\n")]
    aks = text[text.index("  aks)\n"):text.index("  *) die \"TARGET must be lab or aks")]
    assert 'load_env "$DEMO_DIR"\n' in lab and ".env.aks" not in lab
    assert 'load_env "$DEMO_DIR" "$DEMO_DIR/.env.aks"' in aks
    assert aks.index("$AKS_REFUSED_ENV") < aks.index("load_env") < aks.index("aks_env_check")
    # exported for the Python children on aks only (the lab environment as before)
    assert ('TARGET="$GPOS_SELECTED_TARGET"\n' in text
            and 'if [ "$TARGET" = aks ]; then export TARGET; fi' in text)


def test_kubectl_only_through_the_lib_wrapper() -> None:
    """No script but lib.sh picks a kubeconfig or context: on aks every `kubectl` is the
    lib.sh function (AKS kubeconfig + context), in the lab the plain binary as before."""
    for path in SHELL:
        code = "\n".join(code_lines(path))
        if path.name == "lib.sh":
            assert code.count("command kubectl") == 2
            continue
        assert "command kubectl" not in code, path.name
        assert "--kubeconfig" not in code and "--context" not in code, path.name
        assert "KUBECONFIG" not in code, path.name


def test_no_script_reads_an_env_file_itself() -> None:
    for path in SHELL:
        if path.name in ("lib.sh", "check_hygiene.sh"):
            continue
        code = "\n".join(code_lines(path))
        assert not re.search(r'(^|[;&|]\s*)\.\s+\S*\.env', code, re.M), path.name
        assert "source " not in code, path.name


def test_install_parts_per_target() -> None:
    text = (SCRIPTS / "install.sh").read_text()
    dispatch = text[text.index('case "$PART" in'):]
    assert "  pg) install_pg ;;" in dispatch
    aks_all = dispatch[dispatch.index('if [ "$TARGET" = aks ]'):dispatch.index("else")]
    lab_all = dispatch[dispatch.index("else"):dispatch.index("fi ;;")]
    assert "install_pg; install_db; install_k8s; install_mesh" in aks_all
    assert "install_db; install_k8s; install_mesh" in lab_all and "install_pg" not in lab_all
    pg = text[text.index("install_pg() {"):text.index("# --------", text.index("install_pg() {"))]
    assert pg.index('if [ "$TARGET" != aks ]') < pg.index("return 0") < pg.index("kubectl")
    assert "--ignore-not-found -o name" in pg and "openssl rand -hex 24" in pg
    # jq emits the Secret only for a 48-hex password: never an empty one kept for good
    assert 'test("^[0-9a-f]{48}$")' in pg and "--from-file=password" not in pg
    assert pg.index("apply_namespace") < pg.index("gpos-postgres-admin") \
        < pg.index('kubectl apply -k "$dir"') < pg.index("rollout status sts/gpos-postgres")


def test_install_k8s_lab_only_steps_and_aks_image() -> None:
    text = (SCRIPTS / "install.sh").read_text()
    k8s = text[text.index("install_k8s() {"):text.index("# ------", text.index("install_k8s() {"))]
    assert 'local overlay="$DEMO_DIR/k8s/overlays/$TARGET"' in k8s
    assert 'kubectl kustomize "$overlay"' in k8s and '"$DEMO_DIR/k8s"' not in k8s
    # --image only on aks; Kyverno wait, Certificate wait and lab CA only in the lab
    aks_head = k8s[k8s.index('if [ "$TARGET" = aks ]; then'):k8s.index("apply_namespace")]
    assert 'image_args=(--image "$GPOS_IMAGE:$GPOS_VERSION")' in aks_head
    assert "db_exists_or_die" in aks_head and k8s.count("image_args=(") == 2
    kyverno = k8s.index("registry-pull-secret")
    assert k8s.rfind("else", 0, kyverno) > k8s.index("apply_acr_pull")
    tls = k8s.index('if [ "$TARGET" = aks ]; then  # TLS')
    assert tls < k8s.index("certificate/gpos-demo") and tls < k8s.index("lab-ca.crt")
    assert "return 0" in k8s[tls:k8s.index("certificate/gpos-demo")]
    # aks: gpos-broker from the Key Vault through pipes (no broker env file); lab as before
    broker = k8s[k8s.index('if [ "$TARGET" = aks ]; then  # the Key Vault password'):]
    broker = broker[:broker.index("  fi\n") + 5]
    assert broker.index("apply_broker_secret") < broker.index("else") \
        < broker.index("--write-broker-env") < broker.index("apply_secret gpos-broker")
    db = text[text.index("install_db() {"):text.index("}\n", text.index("install_db() {"))]
    assert db.index('= kubectl ]') < db.index("pg_ready") < db.index("else") \
        < db.index("docker inspect")


def test_makefile_kubectl_recipes_use_the_target_wrapper() -> None:
    text = (ROOT / "Makefile").read_text()
    recipes = [ln for ln in text.splitlines() if ln.startswith("\t")]
    assert not [ln for ln in recipes if re.match(r"\s*@?kubectl\b", ln)]
    assert "\t$(KUBECTL) -n $(NS) get pods -o wide" in recipes
    assert "CTL := $(KUBECTL) -n $(NS) exec deploy/gpos-ui" in text
    assert "KUBECTL := bash -c '. scripts/lib.sh && kubectl \"$$@\"' kubectl" in text
    assert text.index("ifeq ($(TARGET),aks)") < text.index("export TARGET")   # aks only
