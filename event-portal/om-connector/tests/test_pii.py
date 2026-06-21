"""Pure PII-signal detection tests (Wave 5 / #62).

connector.pii has no OM-SDK dependency, so the security-critical logic is
fully unit-tested here -- including ``should_sample()``, the pure gate that
backs the sample-data hard-block (a PII topic is never sampled). The OM
TagLabel rendering that consumes these signals lives in modules that need
the SDK and is covered in the Docker test image."""
import json

from connector import pii


def test_topic_address_regex_match_and_blank_pattern():
    assert pii.topic_address_is_pii("orders/pii/created", "pii") is True
    assert pii.topic_address_is_pii("orders/created", "pii") is False
    # Blank pattern disables the signal.
    assert pii.topic_address_is_pii("orders/pii/created", "") is False
    assert pii.topic_address_is_pii(None, "pii") is False


def test_topic_address_invalid_regex_is_safe_nomatch():
    # A bad pattern must NOT raise and must NOT match-everything.
    assert pii.topic_address_is_pii("anything", "([unclosed") is False


def test_names_intersect():
    assert pii.names_intersect(["DataClass", "pii"], ["pii"]) is True
    assert pii.names_intersect(["DataClass"], ["pii"]) is False
    assert pii.names_intersect(["pii"], []) is False
    assert pii.names_intersect(None, ["pii"]) is False


def test_json_schema_x_pii_fields_nested():
    schema = json.dumps({
        "type": "object",
        "properties": {
            "email": {"type": "string", "x-pii": True},
            "name": {"type": "string"},
            "address": {
                "type": "object",
                "properties": {
                    "zip": {"type": "string", "x-pii": "true"},
                    "country": {"type": "string"},
                },
            },
        },
    })
    fields = pii.schema_text_pii_fields(schema, "JSON")
    assert fields == {"email", "zip"}


def test_avro_x_pii_via_property_and_doc():
    schema = json.dumps({
        "type": "record",
        "name": "Customer",
        "fields": [
            {"name": "ssn", "type": "string", "x-pii": True},
            {"name": "note", "type": "string", "doc": "free text, contains x-pii"},
            {"name": "id", "type": "string"},
        ],
    })
    fields = pii.schema_text_pii_fields(schema, "AVRO")
    assert fields == {"ssn", "note"}


def test_schema_text_malformed_is_empty_set():
    assert pii.schema_text_pii_fields("{not json", "JSON") == set()
    assert pii.schema_text_pii_fields("", "JSON") == set()
    assert pii.schema_text_pii_fields(None, "AVRO") == set()


def test_has_pii_signal_each_source_independently():
    # CA-name signal
    assert pii.has_pii_signal(present_ca_names=["pii"], pii_ca_names=["pii"]) is True
    # tag signal
    assert pii.has_pii_signal(
        present_tag_names=["Compliance.PII"], pii_tag_names=["Compliance.PII"]
    ) is True
    # topic-segment signal
    assert pii.has_pii_signal(topic_address="a/pii/b", topic_pattern="pii") is True
    # schema x-pii signal
    assert pii.has_pii_signal(
        schema_text=json.dumps(
            {"properties": {"email": {"x-pii": True}}}
        ),
        schema_type="JSON",
    ) is True
    # nothing configured / present -> no PII
    assert pii.has_pii_signal(
        present_ca_names=["other"], pii_ca_names=["pii"],
        topic_address="a/b", topic_pattern="pii",
    ) is False


def test_should_sample_never_samples_pii():
    """The security gate: a PII topic is never buffered for sampling,
    no matter the other flags; an inversion of this must fail the test."""
    assert pii.should_sample(True, True, False) is True       # clean topic -> sample
    assert pii.should_sample(True, True, True) is False        # PII -> NEVER
    assert pii.should_sample(False, True, False) is False      # sampling off
    assert pii.should_sample(True, False, False) is False      # no address
    assert pii.should_sample(False, False, True) is False


def test_parse_pii_ca_names_forms():
    assert pii.parse_pii_ca_names("pii") == ["pii"]
    assert pii.parse_pii_ca_names("a, b ,c") == ["a", "b", "c"]
    assert pii.parse_pii_ca_names(["x", "y"]) == ["x", "y"]
    assert pii.parse_pii_ca_names("") == []
    assert pii.parse_pii_ca_names(None) == []
