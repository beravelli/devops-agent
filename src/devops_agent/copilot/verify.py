"""Verify that an incoming request really came from GitHub Copilot.

GitHub signs the raw request body with an ECDSA P-256 key (algorithm
ECDSA-NIST-P256V1-SHA256). The request carries the key id and signature in
headers; the matching public key is published at GitHub's metadata endpoint.

Critical: verify against the *raw* bytes of the body, never a re-serialized
JSON, or the signature will never match.
"""

from __future__ import annotations

import base64
import time
from typing import Callable, Mapping

import httpx

PUBLIC_KEYS_URL = "https://api.github.com/meta/public_keys/copilot_api"

# Current headers carry the X-GitHub- prefix; the un-prefixed pair is the
# deprecated legacy form. Accept either, preferring the current one.
_SIGNATURE_HEADERS = ("x-github-public-key-signature", "github-public-key-signature")
_KEY_ID_HEADERS = ("x-github-public-key-identifier", "github-public-key-identifier")

_KEYS_CACHE: dict[str, object] = {"fetched_at": 0.0, "keys": {}}
_CACHE_TTL = 3600.0


class SignatureError(Exception):
    """Raised when a request cannot be verified as coming from GitHub."""


def extract_signature_headers(headers: Mapping[str, str]) -> tuple[str | None, str | None]:
    """Return (key_identifier, signature) from request headers, or (None, None)."""
    lower = {k.lower(): v for k, v in headers.items()}
    key_id = next((lower[h] for h in _KEY_ID_HEADERS if h in lower), None)
    signature = next((lower[h] for h in _SIGNATURE_HEADERS if h in lower), None)
    return key_id, signature


def fetch_public_keys(token: str | None = None, force: bool = False) -> dict[str, str]:
    """Fetch GitHub's Copilot public keys as {key_identifier: pem}. Cached for an hour."""
    now = time.time()
    if not force and _KEYS_CACHE["keys"] and now - float(_KEYS_CACHE["fetched_at"]) < _CACHE_TTL:
        return _KEYS_CACHE["keys"]  # type: ignore[return-value]
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resp = httpx.get(PUBLIC_KEYS_URL, headers=headers, timeout=10.0)
    resp.raise_for_status()
    data = resp.json()
    keys = {entry["key_identifier"]: entry["key"] for entry in data.get("public_keys", [])}
    _KEYS_CACHE.update(fetched_at=now, keys=keys)
    return keys


def _default_key_resolver(key_id: str | None, token: str | None = None) -> str:
    keys = fetch_public_keys(token=token)
    if key_id and key_id in keys:
        return keys[key_id]
    # Refresh once in case the key rotated, then fall back to any current key.
    keys = fetch_public_keys(token=token, force=True)
    if key_id and key_id in keys:
        return keys[key_id]
    if keys:
        return next(iter(keys.values()))
    raise SignatureError("no GitHub public keys available to verify the request")


def verify_signature(
    raw_body: bytes,
    key_id: str | None,
    signature_b64: str | None,
    key_resolver: Callable[[str | None], str] | None = None,
) -> None:
    """Verify the request body signature. Raises SignatureError on any failure.

    `key_resolver` maps a key id to a PEM public key; defaults to fetching from
    GitHub. Tests inject a local resolver to avoid network access.
    """
    if not signature_b64:
        raise SignatureError("missing signature header")
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise SignatureError(
            "the 'cryptography' package is required for Copilot signature "
            "verification. Install the server extra: uv sync --extra server"
        ) from exc

    resolver = key_resolver or _default_key_resolver
    pem = resolver(key_id)
    try:
        public_key = serialization.load_pem_public_key(pem.encode())
        signature = base64.b64decode(signature_b64)
        public_key.verify(signature, raw_body, ec.ECDSA(hashes.SHA256()))  # type: ignore[union-attr]
    except InvalidSignature as exc:
        raise SignatureError("request signature does not match GitHub's public key") from exc
    except Exception as exc:  # malformed key/signature
        raise SignatureError(f"signature verification failed: {exc}") from exc
