"""config: typed settings from the environment (3.1)."""

from __future__ import annotations

from datetime import date

import pytest

from gposdemo.common.config import DEFAULT_PORTS, Settings, load_settings


def test_lab_defaults_from_an_empty_environment() -> None:
    s = load_settings("engine", {})
    assert s.demo_date == date(2027, 2, 16)
    assert (s.tz, s.country, s.company) == ("Europe/Berlin", "DE", "999")
    assert s.booth_location == "Root.DE.999.101.01"
    assert s.test_location == "Root.DE.999.199.99"
    assert s.probe_location == "Root.DE.999.199.98"
    assert (s.delivery, s.bus_kind) == ("direct", "solace")
    assert (s.solace_host, s.solace_vpn) == ("tcp://host.docker.internal:55557", "default")
    assert (s.pos_grpc, s.wws_grpc, s.loyalty_grpc) == (
        "gpos-pos:50051", "gpos-wws:50053", "gpos-loyalty:50052")
    assert s.engine_url == "http://gpos-engine:8765"
    assert s.pos_admin_url == "http://gpos-pos:8771"
    assert (s.stale_seconds, s.close_max_age_seconds, s.proposal_expiry_seconds) == (20, 300, 150)
    assert (s.gate_min_delay_s, s.gate_guard, s.tool_store) == (3.0, "block", "101")
    assert s.hil_timeout_s == 120.0  # = hil.timeout "2m" of the gate (11.5)
    assert s.log_level == "INFO"
    assert s.gebit_descriptor_sets == []


@pytest.mark.parametrize(("service", "ports"), [
    ("pos", (50051, 8771, 8771)), ("wws", (50053, 8773, 8773)),
    ("loyalty", (50052, 8772, 8772)), ("engine", (0, 8765, 8765)),
    ("gate", (0, 8766, 8766)), ("ui", (0, 0, 8090)), ("ctl", (0, 0, 0)),
])
def test_ports_per_service(service: str, ports: tuple[int, int, int]) -> None:
    s = load_settings(service, {})
    assert (s.grpc_port, s.mcp_port, s.http_port) == ports


def test_ports_are_unique_across_services() -> None:
    used = [p for ports in DEFAULT_PORTS.values() for p in set(ports) if p]
    assert len(used) == len(set(used))


def test_environment_overrides_and_parsing() -> None:
    env = {"GPOS_DEMO_DATE": "2027-02-17", "GPOS_BUS": "memory", "GPOS_DELIVERY": "Persistent",
           "GEBIT_DESCRIPTOR_SETS": "/d/purchase-api-2.50.0.pb:/d/receipt-api-2.13.0.pb",
           "GRPC_PORT": "50999", "GATE_MIN_DELAY_S": "2.5", "GATE_GUARD": "f2",
           "ENGINE_URL": "http://localhost:8765/", "GPOS_TOOL_STORE": "199",
           "LOG_LEVEL": "debug", "HIL_TIMEOUT_S": "4"}
    s = load_settings("pos", env)
    assert s.demo_date == date(2027, 2, 17)
    assert (s.bus_kind, s.delivery, s.gate_guard) == ("memory", "persistent", "f2")
    assert s.gebit_descriptor_sets == ["/d/purchase-api-2.50.0.pb", "/d/receipt-api-2.13.0.pb"]
    assert (s.grpc_port, s.mcp_port) == (50999, 8771)
    assert s.gate_min_delay_s == 2.5
    assert s.hil_timeout_s == 4.0
    assert s.engine_url == "http://localhost:8765"
    assert (s.tool_store, s.log_level) == ("199", "DEBUG")


@pytest.mark.parametrize(("key", "value"), [
    ("GPOS_DEMO_DATE", "16.02.2027"), ("GPOS_TZ", "Mars/Olympus"), ("GPOS_BUS", "kafka"),
    ("GPOS_DELIVERY", "guaranteed"), ("GATE_GUARD", "off"), ("GRPC_PORT", "x"),
    ("GATE_MIN_DELAY_S", "drei"), ("HIL_TIMEOUT_S", "2m"),
    ("GPOS_BOOTH_LOCATION", "DE.999.101.01"),
])
def test_invalid_values_name_the_variable(key: str, value: str) -> None:
    with pytest.raises(ValueError, match=key):
        load_settings("engine", {key: value})


def test_secrets_stay_out_of_repr() -> None:
    s = load_settings("wws", {"SOLACE_PASSWORD": "pw-geheim-123",
                              "GPOS_DSN": "postgresql://gpos_wws:dsn-geheim@h:5432/gpos"})
    assert s.solace_password == "pw-geheim-123"
    assert "geheim" not in repr(s)


def test_settings_have_no_model_endpoint_or_key_fields() -> None:
    """Hard rule 1: SAM owns the models; no service setting names a key or an endpoint."""
    names = set(Settings.__dataclass_fields__)
    assert not {n for n in names if "llm" in n or "key" in n or "vision" in n or "model" in n}


def test_fixture_settings_are_the_test_profile(settings: Settings) -> None:
    assert settings.bus_kind == "memory"
    assert settings.tool_store == "199"
    assert settings.showcase_descriptor_set.endswith("build/descriptors/showcase.pb")
    assert settings.zone.key == "Europe/Berlin"
