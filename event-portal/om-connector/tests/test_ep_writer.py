"""EventPortalWriter tests (Wave 4.5 / #49).

Mocks the EP REST API with ``responses`` to lock the write client's
behaviour. NOTE: this verifies OUR request shape, not that live EP v2
accepts it -- the contract is marked for verification under shadow deploy.
"""
import pytest

responses = pytest.importorskip("responses")

from connector.event_portal_client import (  # noqa: E402
    EventPortalAuthError,
    EventPortalWriter,
)

BASE = "https://api.solace.cloud/api/v2"


def test_constructor_requires_writer_token():
    with pytest.raises(EventPortalAuthError):
        EventPortalWriter(writer_token="")


@responses.activate
def test_set_entity_custom_attributes_patches_entity():
    responses.add(
        responses.PATCH,
        f"{BASE}/architecture/applicationVersions/av-1",
        json={"data": {"id": "av-1"}},
        status=200,
    )
    w = EventPortalWriter(writer_token="wtok")
    out = w.set_entity_custom_attributes(
        "applicationVersions", "av-1",
        [{"name": "epCertification", "value": "Certification.Gold"}],
    )
    assert out == {"data": {"id": "av-1"}}
    body = responses.calls[0].request.body
    assert b"epCertification" in (body if isinstance(body, bytes) else body.encode())


@responses.activate
def test_set_entity_custom_attributes_401_raises_auth_error():
    responses.add(
        responses.PATCH,
        f"{BASE}/architecture/eventVersions/ev-1",
        status=401,
    )
    w = EventPortalWriter(writer_token="wtok")
    with pytest.raises(EventPortalAuthError):
        w.set_entity_custom_attributes("eventVersions", "ev-1", [])


@responses.activate
def test_ensure_ca_definition_skips_when_present():
    responses.add(
        responses.GET,
        f"{BASE}/architecture/customAttributeDefinitions",
        json={"data": [{"id": "d1", "name": "epCertification"}]},
        status=200,
    )
    w = EventPortalWriter(writer_token="wtok")
    out = w.ensure_custom_attribute_definition("epCertification", ["application"])
    assert out["id"] == "d1"
    # No POST was made (only the GET).
    assert len(responses.calls) == 1


@responses.activate
def test_ensure_ca_definition_creates_when_missing():
    responses.add(
        responses.GET,
        f"{BASE}/architecture/customAttributeDefinitions",
        json={"data": []},
        status=200,
    )
    responses.add(
        responses.POST,
        f"{BASE}/architecture/customAttributeDefinitions",
        json={"data": {"id": "new", "name": "epExtendedDescription"}},
        status=201,
    )
    w = EventPortalWriter(writer_token="wtok")
    out = w.ensure_custom_attribute_definition(
        "epExtendedDescription", ["application", "event"]
    )
    assert out["id"] == "new"
    assert responses.calls[1].request.method == "POST"
