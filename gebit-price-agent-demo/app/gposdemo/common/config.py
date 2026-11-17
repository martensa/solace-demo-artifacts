"""Typed settings of every gpos-demo process (UC1-BUILD-SPEC 3.1).

All values come from the process environment (ConfigMap ``gpos-config`` and the
Secrets ``gpos-broker``, ``gpos-db`` in the cluster). Defaults are the lab values of
3.1, so a pod only needs what differs. Secrets (``SOLACE_PASSWORD``, ``GPOS_DSN``) are
kept out of ``repr`` and are never logged.

There is deliberately no setting for an LLM endpoint, LLM key or vision model.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SERVICES = ("pos", "wws", "loyalty", "engine", "gate", "ui")
DELIVERY_MODES = ("direct", "persistent")
BUS_KINDS = ("solace", "memory")
GATE_GUARDS = ("block", "warn", "f2")

# service -> (grpc_port, mcp_port, http_port); MCP and HTTP share one port (2.2)
DEFAULT_PORTS: dict[str, tuple[int, int, int]] = {
    "pos": (50051, 8771, 8771),
    "wws": (50053, 8773, 8773),
    "loyalty": (50052, 8772, 8772),
    "engine": (0, 8765, 8765),
    "gate": (0, 8766, 8766),
    "ui": (0, 0, 8090),
}

IMAGE_SHOWCASE_SET = "/app/descriptors/showcase.pb"
IMAGE_POLICY_FILE = "/app/policy/pricing-policy.yaml"
IMAGE_DATA_DIR = "/app/data"


def repo_root() -> Path:
    """The demo root (``gebit-price-agent-demo/``) when running from a checkout.

    ``app/gposdemo/common/config.py`` -> three levels up. Inside the image the
    result is ``/``, which has no ``proto/`` directory; callers check for that.
    """
    return Path(__file__).resolve().parents[3]


def local_showcase_set() -> Path:
    """Where ``python -m gposdemo.common.protoc`` writes the descriptor set (12.2)."""
    return repo_root() / "build" / "descriptors" / "showcase.pb"


@dataclass(frozen=True)
class Settings:
    """Configuration of one process. Build it with :func:`load_settings`."""

    service: str
    demo_date: date
    tz: str
    country: str
    company: str
    booth_location: str
    test_location: str
    probe_location: str
    delivery: str
    bus_kind: str
    solace_host: str
    solace_vpn: str
    solace_username: str
    solace_password: str = field(repr=False)
    dsn: str = field(repr=False)
    gebit_descriptor_sets: list[str] = field(default_factory=list)
    showcase_descriptor_set: str = IMAGE_SHOWCASE_SET
    pos_grpc: str = "gpos-pos:50051"
    wws_grpc: str = "gpos-wws:50053"
    loyalty_grpc: str = "gpos-loyalty:50052"
    engine_url: str = "http://gpos-engine:8765"
    pos_admin_url: str = "http://gpos-pos:8771"
    grpc_port: int = 0
    mcp_port: int = 0
    http_port: int = 0
    policy_file: str = IMAGE_POLICY_FILE
    data_dir: str = IMAGE_DATA_DIR
    stale_seconds: int = 20
    close_max_age_seconds: int = 300
    proposal_expiry_seconds: int = 150
    gate_min_delay_s: float = 3.0
    hil_timeout_s: float = 120.0  # = hil.timeout "2m" of the gate; set only in tests (11.5)
    gate_guard: str = "block"
    tool_store: str = "101"
    log_level: str = "INFO"
    sam_url: str = "https://sam.solace.lab"

    @property
    def zone(self) -> ZoneInfo:
        """``GPOS_TZ`` as a :class:`zoneinfo.ZoneInfo`."""
        return ZoneInfo(self.tz)


def _image_or_repo(image_path: str, repo_path: Path) -> str:
    """Image path when it exists (or no checkout is around), else the checkout path."""
    if Path(image_path).exists() or not repo_path.exists():
        return image_path
    return str(repo_path)


def _int(env: Mapping[str, str], key: str, default: int) -> int:
    raw = env.get(key, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{key} must be an integer, got {raw!r}") from exc


def _float(env: Mapping[str, str], key: str, default: float) -> float:
    raw = env.get(key, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{key} must be a number, got {raw!r}") from exc


def _choice(env: Mapping[str, str], key: str, default: str, allowed: tuple[str, ...]) -> str:
    value = env.get(key, "").strip().lower() or default
    if value not in allowed:
        raise ValueError(f"{key} must be one of {allowed}, got {value!r}")
    return value


def _location(env: Mapping[str, str], key: str, default: str) -> str:
    value = env.get(key, "").strip() or default
    parts = value.split(".")
    if len(parts) != 5 or parts[0] != "Root" or not all(parts[1:]):
        raise ValueError(f"{key} must look like Root.DE.999.101.01, got {value!r}")
    return value


def _demo_date(env: Mapping[str, str]) -> date:
    raw = env.get("GPOS_DEMO_DATE", "").strip() or "2027-02-16"
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"GPOS_DEMO_DATE must be an ISO date, got {raw!r}") from exc


def _tz(env: Mapping[str, str]) -> str:
    value = env.get("GPOS_TZ", "").strip() or "Europe/Berlin"
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"GPOS_TZ is not a known time zone: {value!r}") from exc
    return value


def _paths(raw: str) -> list[str]:
    return [p for p in raw.split(os.pathsep) if p.strip()]


def load_settings(service: str, env: Mapping[str, str] | None = None) -> Settings:
    """Read the settings of ``service`` from ``env`` (default: ``os.environ``).

    ``service`` is one of :data:`SERVICES` for the six commands; any other name (e.g.
    ``"ctl"`` or ``"test"``) is accepted and gets no default ports. Raises
    ``ValueError`` with the variable name on an invalid value.
    """
    env = os.environ if env is None else env
    grpc_port, mcp_port, http_port = DEFAULT_PORTS.get(service, (0, 0, 0))
    root = repo_root()
    return Settings(
        service=service,
        demo_date=_demo_date(env),
        tz=_tz(env),
        country=env.get("GPOS_COUNTRY", "").strip() or "DE",
        company=env.get("GPOS_COMPANY", "").strip() or "999",
        booth_location=_location(env, "GPOS_BOOTH_LOCATION", "Root.DE.999.101.01"),
        test_location=_location(env, "GPOS_TEST_LOCATION", "Root.DE.999.199.99"),
        probe_location=_location(env, "GPOS_PROBE_LOCATION", "Root.DE.999.199.98"),
        delivery=_choice(env, "GPOS_DELIVERY", "direct", DELIVERY_MODES),
        bus_kind=_choice(env, "GPOS_BUS", "solace", BUS_KINDS),
        solace_host=env.get("SOLACE_HOST", "").strip() or "tcp://host.docker.internal:55557",
        solace_vpn=env.get("SOLACE_VPN", "").strip() or "default",
        solace_username=env.get("SOLACE_USERNAME", ""),
        solace_password=env.get("SOLACE_PASSWORD", ""),
        dsn=env.get("GPOS_DSN", ""),
        gebit_descriptor_sets=_paths(env.get("GEBIT_DESCRIPTOR_SETS", "")),
        showcase_descriptor_set=env.get("SHOWCASE_DESCRIPTOR_SET", "").strip()
        or _image_or_repo(IMAGE_SHOWCASE_SET, local_showcase_set()),
        pos_grpc=env.get("POS_GRPC", "").strip() or "gpos-pos:50051",
        wws_grpc=env.get("WWS_GRPC", "").strip() or "gpos-wws:50053",
        loyalty_grpc=env.get("LOYALTY_GRPC", "").strip() or "gpos-loyalty:50052",
        engine_url=(env.get("ENGINE_URL", "").strip() or "http://gpos-engine:8765").rstrip("/"),
        pos_admin_url=(env.get("POS_ADMIN_URL", "").strip() or "http://gpos-pos:8771").rstrip("/"),
        grpc_port=_int(env, "GRPC_PORT", grpc_port),
        mcp_port=_int(env, "MCP_PORT", mcp_port),
        http_port=_int(env, "HTTP_PORT", http_port),
        policy_file=env.get("POLICY_FILE", "").strip()
        or _image_or_repo(IMAGE_POLICY_FILE, root / "policy" / "pricing-policy.yaml"),
        data_dir=env.get("DATA_DIR", "").strip() or _image_or_repo(IMAGE_DATA_DIR, root / "data"),
        stale_seconds=_int(env, "STALE_SECONDS", 20),
        close_max_age_seconds=_int(env, "CLOSE_MAX_AGE_SECONDS", 300),
        proposal_expiry_seconds=_int(env, "PROPOSAL_EXPIRY_SECONDS", 150),
        gate_min_delay_s=_float(env, "GATE_MIN_DELAY_S", 3.0),
        hil_timeout_s=_float(env, "HIL_TIMEOUT_S", 120.0),
        gate_guard=_choice(env, "GATE_GUARD", "block", GATE_GUARDS),
        tool_store=env.get("GPOS_TOOL_STORE", "").strip() or "101",
        log_level=(env.get("LOG_LEVEL", "").strip() or "INFO").upper(),
        sam_url=(env.get("SAM_URL", "").strip() or "https://sam.solace.lab").rstrip("/"),
    )
