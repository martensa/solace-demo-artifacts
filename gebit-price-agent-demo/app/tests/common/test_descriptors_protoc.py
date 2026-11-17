"""descriptors and protoc: the Showcase set from proto/** (4.1, 4.3, 4.4, 12.2)."""

from __future__ import annotations

import difflib
import re
from pathlib import Path

import pytest
from google.protobuf import descriptor_pb2
from google.protobuf.descriptor_pool import DescriptorPool

from gposdemo.common import descriptors, protoc
from gposdemo.common.descriptors import Types, load_pool

REPO = Path(__file__).resolve().parents[3]
SPEC = REPO / "UC1-BUILD-SPEC.md"
SPIKE_LOYALTY = REPO / "spikes" / "loyalty-proto"


def test_build_is_reproducible(tmp_path: Path, showcase_set: Path) -> None:
    out = protoc.build_descriptor_set(tmp_path / "showcase.pb")
    assert out.read_bytes() == showcase_set.read_bytes()
    fds = descriptor_pb2.FileDescriptorSet.FromString(out.read_bytes())
    names = [f.name for f in fds.file]
    assert "google/protobuf/empty.proto" in names  # --include_imports
    assert len([n for n in names if n.startswith("de/showcase/")]) == 16
    assert not [f for f in fds.file if f.package.startswith("de.gebit")]


def test_showcase_services(showcase_pool: DescriptorPool) -> None:
    wws = showcase_pool.FindServiceByName(descriptors.WWS_SVC)
    assert [m.name for m in wws.methods] == [
        "ListArticles", "GetArticle", "GetEffectivePrice", "GetSalesPerformance",
        "GetSeasonInfo", "GetPriceHistory", "RequestPriceChange", "EndPriceChange",
        "ResetDemoState"]
    loyalty = showcase_pool.FindServiceByName(descriptors.LOYALTY_SVC)
    method = loyalty.methods_by_name["GetPurchaseBehaviour"]
    assert method.input_type.full_name == "de.showcase.loyalty.v1.query.GetPurchaseBehaviour"
    assert method.output_type.full_name == "de.showcase.loyalty.v1.datatype.PurchaseBehaviour"


def test_uc1_loyalty_additions(showcase_pool: DescriptorPool) -> None:
    profile = showcase_pool.FindMessageTypeByName(
        "de.showcase.loyalty.v1.datatype.MemberProfile")
    assert profile.fields_by_name["segment_label"].number == 10
    behaviour = showcase_pool.FindMessageTypeByName(
        "de.showcase.loyalty.v1.datatype.PurchaseBehaviour")
    assert [(f.name, f.number) for f in behaviour.fields] == [
        ("membership_id", 1), ("article_number", 2), ("consent_profiling", 3),
        ("persona_label", 4), ("segment_label", 5), ("member_purchases_8w", 6),
        ("member_purchases_12w", 7), ("days_since_last", 8), ("median_interval_days", 9),
        ("cardholder_weekly", 10), ("cardholder_drop_pct", 11)]


def _spec_blocks() -> dict[str, str]:
    text = SPEC.read_text(encoding="utf-8")
    blocks = re.findall(r"```proto\n(.*?)```", text, flags=re.S)
    out = {}
    for block in blocks:
        match = re.match(r"// (proto/de/showcase/wws/v1/\S+\.proto)\n", block)
        if match:
            out[match.group(1)] = block
    return out


def test_wws_protos_are_verbatim_from_the_spec() -> None:
    blocks = _spec_blocks()
    assert len(blocks) == 5
    for rel, block in blocks.items():
        assert (REPO / rel).read_text(encoding="utf-8") == block, rel


@pytest.mark.skipif(not SPIKE_LOYALTY.is_dir(), reason="spike protos not present")
def test_loyalty_protos_only_add_lines_to_the_spike_files() -> None:
    spike_files = sorted(SPIKE_LOYALTY.rglob("*.proto"))
    assert len(spike_files) == 11
    changed = set()
    for spike in spike_files:
        ours = REPO / "proto" / spike.relative_to(SPIKE_LOYALTY)
        diff = list(difflib.ndiff(spike.read_text(encoding="utf-8").splitlines(),
                                  ours.read_text(encoding="utf-8").splitlines()))
        assert not [d for d in diff if d.startswith("- ")], ours
        if any(d.startswith("+ ") for d in diff):
            changed.add(spike.name)
    assert changed == {"loyalty_query.proto", "loyalty_datatype.proto", "loyalty_service.proto"}


def _set_with(tmp_path: Path, name: str, files: list[descriptor_pb2.FileDescriptorProto]) -> str:
    path = tmp_path / name
    path.write_bytes(descriptor_pb2.FileDescriptorSet(file=files).SerializeToString())
    return str(path)


def _file(name: str, package: str, message: str, deps: tuple[str, ...] = ()
          ) -> descriptor_pb2.FileDescriptorProto:
    fdp = descriptor_pb2.FileDescriptorProto(name=name, package=package, syntax="proto3",
                                             dependency=list(deps))
    fdp.message_type.add(name=message)
    return fdp


def test_load_pool_orders_dependencies_and_dedups(tmp_path: Path) -> None:
    base = _file("t/base.proto", "t", "Base")
    top = _file("t/top.proto", "t", "Top", ("t/base.proto",))
    first = _set_with(tmp_path, "a.pb", [top, base])  # dependency after its user
    second = _set_with(tmp_path, "b.pb", [base])      # identical duplicate is fine
    pool = load_pool([first, second])
    assert Types(pool).new("t.Top").DESCRIPTOR.full_name == "t.Top"


def test_load_pool_rejects_conflicting_files(tmp_path: Path) -> None:
    first = _set_with(tmp_path, "a.pb", [_file("t/base.proto", "t", "Base")])
    second = _set_with(tmp_path, "b.pb", [_file("t/base.proto", "t", "Other")])
    with pytest.raises(ValueError, match="conflicting definitions of t/base.proto"):
        load_pool([first, second])
    with pytest.raises(ValueError):
        load_pool([])


def test_types_cache(showcase_pool: DescriptorPool) -> None:
    types = Types(showcase_pool)
    cls = types.cls("de.showcase.wws.v1.datatype.EffectivePrice")
    assert types.cls("de.showcase.wws.v1.datatype.EffectivePrice") is cls
    assert types.new("de.showcase.wws.v1.datatype.EffectivePrice", pct_shown=20).pct_shown == 20
    with pytest.raises(KeyError):
        types.cls("de.showcase.wws.v1.datatype.Nope")


@pytest.mark.gebit
def test_gebit_pool_stays_separate(gebit_pool: DescriptorPool) -> None:
    svc = gebit_pool.FindServiceByName(descriptors.PURCHASE_SVC)
    assert len(svc.methods) == 106
    for name in ("CreatePurchaseTransaction", "AddArticle", "AssignLoyaltyMembership",
                 "StartPaymentProcess", "CreateCashPayment", "CancelPurchaseTransaction",
                 "VoidArticlePosition"):
        assert name in svc.methods_by_name
    assert Types(gebit_pool).event("PositionAdded").DESCRIPTOR.full_name == (
        f"{descriptors.EVENT_PKG}.PositionAdded")
    with pytest.raises(KeyError):
        gebit_pool.FindServiceByName(descriptors.WWS_SVC)


def test_protoc_main_and_ensure_local(tmp_path: Path, capsys: pytest.CaptureFixture[str],
                                      showcase_set: Path) -> None:
    out = tmp_path / "cli" / "showcase.pb"
    assert protoc.main(["--out", str(out)]) == 0
    assert "16 files" in capsys.readouterr().out
    assert out.read_bytes() == showcase_set.read_bytes()
    fresh = tmp_path / "fresh.pb"
    assert protoc.ensure_local(fresh) == fresh and fresh.exists()
    assert not list(tmp_path.rglob("*.tmp"))
