"""Tests for the GitHub Copilot agent integration: message translation, SSE
formatting, and request signature verification (with a locally generated key so
no network access is needed)."""

from __future__ import annotations

import base64
import json

import pytest

from devops_agent.copilot.protocol import split_messages, sse_stream
from devops_agent.copilot.verify import SignatureError, extract_signature_headers, verify_signature


def test_split_messages_picks_last_user_and_history():
    messages = [
        {"role": "system", "content": "You are Copilot."},
        {"role": "user", "content": "first question"},
        {"role": "assistant", "content": "first answer"},
        {"role": "user", "content": "why are payments pods crashing?"},
    ]
    user_input, history = split_messages(messages)
    assert user_input == "why are payments pods crashing?"
    assert [m.content for m in history] == ["first question", "first answer"]


def test_split_messages_empty():
    assert split_messages([]) == ("", [])
    assert split_messages([{"role": "system", "content": "x"}]) == ("", [])


def test_sse_stream_shape():
    chunks = list(sse_stream("hello world", chunk_size=4))
    assert all(c.startswith("data: ") and c.endswith("\n\n") for c in chunks)
    assert chunks[-1] == "data: [DONE]\n\n"

    # The role chunk comes first; reassembled content equals the input.
    first = json.loads(chunks[0][len("data: ") :])
    assert first["choices"][0]["delta"].get("role") == "assistant"
    content = ""
    for c in chunks[1:-1]:
        payload = json.loads(c[len("data: ") :])
        content += payload["choices"][0]["delta"].get("content", "")
    assert content == "hello world"

    # A stop finish_reason is emitted before [DONE].
    finish = json.loads(chunks[-2][len("data: ") :])
    assert finish["choices"][0]["finish_reason"] == "stop"


def test_extract_signature_headers_prefers_x_github():
    key_id, sig = extract_signature_headers(
        {
            "X-GitHub-Public-Key-Identifier": "current",
            "X-GitHub-Public-Key-Signature": "abc",
            "Github-Public-Key-Identifier": "legacy",
        }
    )
    assert key_id == "current"
    assert sig == "abc"


def _make_keypair():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    private_key = ec.generate_private_key(ec.SECP256R1())
    pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return private_key, pem


def test_verify_signature_roundtrip():
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec

    private_key, pem = _make_keypair()
    body = b'{"messages":[{"role":"user","content":"hi"}]}'
    signature = base64.b64encode(private_key.sign(body, ec.ECDSA(hashes.SHA256()))).decode()

    # Valid signature verifies against the matching key.
    verify_signature(body, "k1", signature, key_resolver=lambda _kid: pem)


def test_verify_signature_rejects_tampered_body():
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec

    private_key, pem = _make_keypair()
    body = b'{"messages":[{"role":"user","content":"hi"}]}'
    signature = base64.b64encode(private_key.sign(body, ec.ECDSA(hashes.SHA256()))).decode()

    with pytest.raises(SignatureError):
        verify_signature(b'{"tampered":true}', "k1", signature, key_resolver=lambda _kid: pem)


def test_verify_signature_requires_signature():
    with pytest.raises(SignatureError):
        verify_signature(b"{}", "k1", None, key_resolver=lambda _kid: "x")
