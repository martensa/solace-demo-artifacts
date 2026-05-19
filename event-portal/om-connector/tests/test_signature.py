import hashlib
import hmac

import pytest

from bridge.signature import SignatureError, verify


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_verify_accepts_matching_signature():
    body = b'{"eventType":"event.updated"}'
    secret = "topsecret"
    verify(body=body, headers={"Solace-Signature": _sign(body, secret)}, secret=secret)


def test_verify_accepts_sha256_prefix():
    body = b'{"eventType":"event.updated"}'
    secret = "topsecret"
    verify(
        body=body,
        headers={"Solace-Signature": f"sha256={_sign(body, secret)}"},
        secret=secret,
    )


def test_verify_accepts_alternate_header():
    body = b"{}"
    secret = "s"
    verify(
        body=body,
        headers={"X-EventPortal-Signature": _sign(body, secret)},
        secret=secret,
    )


def test_verify_rejects_bad_signature():
    with pytest.raises(SignatureError):
        verify(
            body=b"{}",
            headers={"Solace-Signature": "deadbeef"},
            secret="topsecret",
        )


def test_verify_rejects_missing_header():
    with pytest.raises(SignatureError):
        verify(body=b"{}", headers={}, secret="topsecret")


def test_verify_rejects_empty_secret():
    with pytest.raises(SignatureError):
        verify(body=b"{}", headers={"Solace-Signature": "x"}, secret="")
