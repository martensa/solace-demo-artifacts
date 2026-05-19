"""Sample-data tests.

We test the parts that don't require a live broker: BrokerConfig parsing,
the push_to_om path, and the error/skip behaviour. The actual SMF
subscribe loop is tested indirectly by mocking the solace SDK in a
follow-up integration suite (not in the unit tests).
"""
from unittest.mock import MagicMock

from connector.sample_data import (
    BrokerConfig,
    CollectedSample,
    SampleDataCollector,
)


def test_broker_config_returns_none_when_host_missing():
    assert BrokerConfig.from_options({}) is None
    assert BrokerConfig.from_options({"brokerVpn": "x"}) is None


def test_broker_config_detects_tls_via_scheme():
    b = BrokerConfig.from_options(
        {
            "brokerHost": "tcps://broker:55443",
            "brokerVpn": "default",
            "brokerUsername": "u",
            "brokerPassword": "p",
        }
    )
    assert b is not None
    assert b.use_tls is True


def test_broker_config_plain_tcp_no_tls():
    b = BrokerConfig.from_options(
        {
            "brokerHost": "tcp://broker:55555",
            "brokerVpn": "default",
            "brokerUsername": "u",
            "brokerPassword": "p",
        }
    )
    assert b is not None
    assert b.use_tls is False


def test_push_to_om_does_nothing_for_empty_sample():
    om = MagicMock()
    SampleDataCollector.push_to_om(
        om, CollectedSample(topic_fqn="svc.t", topic_address="t/a")
    )
    om.client.put.assert_not_called()
    om.client.get.assert_not_called()


def test_push_to_om_puts_when_messages_present():
    om = MagicMock()
    om.client.get.return_value = {"id": "topic-id"}
    SampleDataCollector.push_to_om(
        om,
        CollectedSample(
            topic_fqn="svc.t",
            topic_address="t/a",
            messages=['{"k":1}', '{"k":2}'],
        ),
    )
    om.client.put.assert_called_once()
    path, kwargs = om.client.put.call_args[0], om.client.put.call_args[1]
    assert path[0] == "/topics/topic-id/sampleData"
    assert kwargs["data"] == {"messages": ['{"k":1}', '{"k":2}']}


def test_push_to_om_silent_when_topic_lookup_fails():
    om = MagicMock()
    om.client.get.side_effect = RuntimeError("404")
    SampleDataCollector.push_to_om(
        om,
        CollectedSample(
            topic_fqn="svc.t", topic_address="t/a", messages=["msg"]
        ),
    )
    om.client.put.assert_not_called()


def test_collect_returns_error_when_not_connected():
    # Build a Collector without calling _connect()
    broker = BrokerConfig(host="tcp://x", vpn="v", username="u", password="p")
    collector = SampleDataCollector.__new__(SampleDataCollector)
    collector.broker = broker
    collector.max_messages = 5
    collector.max_bytes = 100
    collector.timeout = 1
    collector._service = None
    sample = collector.collect("svc.t", "t/a")
    assert sample.error == "not connected"
    assert sample.messages == []
