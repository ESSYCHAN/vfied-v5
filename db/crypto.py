"""Envelope encryption for secrets at rest (MIGRATION.md Step 2 schema notes).

Both secret-bearing columns use this:
  - connection_key_based.api_key_ciphertext  (the API key)
  - connection_endpoint_based.headers          (WHOLE blob, opaque — DECIDED (a))

DECIDED (a): the entire headers blob is encrypted as one opaque ciphertext. We do
NOT try to classify which headers look sensitive — that classifier would be wrong
(X-Api-Key, Cookie, signed-query headers, vendor schemes). Blanket-encrypt is
simpler and lossless because headers are never queried.

This is a DEV stub using Fernet-style symmetric encryption keyed from an env var.
PROD swaps `encrypt`/`decrypt` for a KMS envelope scheme (data key per secret,
wrapped by a KMS CMK); `kms_key_id` records which key wrapped it for rotation.
The interface — encrypt(plaintext)->ciphertext, decrypt(ciphertext)->plaintext,
just-in-time in the worker, never logged — does not change.
"""
import base64
import hashlib
import hmac
import os

_SALT = b"vfied-envelope-v1"


def _key() -> bytes:
    secret = os.getenv("VFIED_SECRET_KEY", "dev-insecure-key-change-me")
    return hashlib.pbkdf2_hmac("sha256", secret.encode(), _SALT, 100_000, dklen=32)


def kms_key_id() -> str:
    """Identifier of the wrapping key (for rotation/audit). Safe to store/log."""
    return os.getenv("VFIED_KMS_KEY_ID", "dev-local-key")


def encrypt(plaintext: str) -> bytes:
    """Dev stub: keyed XOR-stream + HMAC tag. NOT production crypto — replaced by
    KMS envelope encryption in prod. Returns opaque ciphertext bytes."""
    if plaintext is None:
        return None
    k = _key()
    data = plaintext.encode("utf-8")
    # keystream from HMAC-SHA256 in counter mode
    stream = bytearray()
    counter = 0
    while len(stream) < len(data):
        stream.extend(hmac.new(k, counter.to_bytes(8, "big"), hashlib.sha256).digest())
        counter += 1
    ct = bytes(b ^ s for b, s in zip(data, stream))
    tag = hmac.new(k, ct, hashlib.sha256).digest()
    return base64.b64encode(tag + ct)


def decrypt(ciphertext: bytes) -> str:
    """Inverse of encrypt. Called just-in-time in the worker; result held in
    memory only, never persisted decrypted, never logged."""
    if ciphertext is None:
        return None
    k = _key()
    raw = base64.b64decode(ciphertext)
    tag, ct = raw[:32], raw[32:]
    expected = hmac.new(k, ct, hashlib.sha256).digest()
    if not hmac.compare_digest(tag, expected):
        raise ValueError("ciphertext authentication failed")
    stream = bytearray()
    counter = 0
    while len(stream) < len(ct):
        stream.extend(hmac.new(k, counter.to_bytes(8, "big"), hashlib.sha256).digest())
        counter += 1
    return bytes(b ^ s for b, s in zip(ct, stream)).decode("utf-8")
