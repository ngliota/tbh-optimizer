"""Easy Save 3 (ES3) AES decryption + value unwrapping for Taskbar Hero saves.

Scheme (verified against the wiki tool's client-side JS and real save files):
  - AES-128-CBC, PKCS7 padding.
  - First 16 bytes of the file = AES IV, which is ALSO the PBKDF2 salt.
  - key = PBKDF2(password, salt=IV, iterations=100, hash=SHA-1, dkLen=16)
  - decrypted bytes are UTF-8 JSON directly (no gzip).

ES3 wraps every value as {"__type": ..., "value": ...} and nested `value`s are
themselves JSON strings, so a recursive unwrap is needed (mirrors the wiki's o()).

Provenance: the password used to decrypt comes from the public client-side JS of the
community tool taskbarhero.wiki/my-save (user-authorized). It touches no game process
and reads only a copy of the save. See password_resolver.py for rotation handling.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


class ES3Error(Exception):
    """Raised when a buffer cannot be decrypted/parsed as a valid ES3 save."""


IV_SIZE = 16
KEY_SIZE = 16
PBKDF2_ITERATIONS = 100


def _derive_key(password: str, iv: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha1", password.encode("utf-8"), iv, PBKDF2_ITERATIONS, KEY_SIZE)


def _pkcs7_unpad(data: bytes) -> bytes:
    if not data:
        raise ES3Error("empty plaintext")
    pad = data[-1]
    if pad < 1 or pad > 16 or pad > len(data):
        raise ES3Error("bad PKCS7 padding")
    if data[-pad:] != bytes([pad]) * pad:
        raise ES3Error("bad PKCS7 padding bytes")
    return data[:-pad]


def decrypt_to_text(buf: bytes, password: str) -> str:
    """Decrypt raw .es3 bytes to the UTF-8 JSON string. Raises ES3Error on failure."""
    if len(buf) <= IV_SIZE:
        raise ES3Error("file too small to be an .es3 save")
    iv, ct = buf[:IV_SIZE], buf[IV_SIZE:]
    if len(ct) % 16 != 0:
        raise ES3Error("ciphertext length not a multiple of the AES block size")
    key = _derive_key(password, iv)
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    try:
        padded = decryptor.update(ct) + decryptor.finalize()
        plain = _pkcs7_unpad(padded)
        return plain.decode("utf-8")
    except (ES3Error, UnicodeDecodeError) as exc:
        # Wrong password or not a TBH save. (The password can change after a game update.)
        raise ES3Error(f"decryption failed (wrong password or not a TBH save): {exc}") from exc


def _maybe_parse_json(text: str) -> Any:
    s = text.strip()
    if s[:1] in "{[":
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            return text
    return text


def unwrap(value: Any) -> Any:
    """Recursively unwrap ES3 {__type, value} wrappers, re-parsing nested JSON strings.

    Mirrors the wiki tool's o() reviver: a wrapped string value that looks like JSON is
    parsed; lists/dicts are walked so the whole tree comes out as native Python objects.
    """
    if isinstance(value, dict):
        if "__type" in value and "value" in value:
            inner = value["value"]
            if isinstance(inner, str):
                return unwrap(_maybe_parse_json(inner))
            return unwrap(inner)
        return {k: unwrap(v) for k, v in value.items()}
    if isinstance(value, list):
        return [unwrap(v) for v in value]
    if isinstance(value, str):
        parsed = _maybe_parse_json(value)
        return unwrap(parsed) if not isinstance(parsed, str) else value
    return value


def decrypt_save(buf: bytes, password: str) -> dict:
    """Decrypt + JSON-parse + recursively unwrap a save buffer into native objects."""
    text = decrypt_to_text(buf, password)
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ES3Error(f"decrypted data is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ES3Error("decrypted root is not a JSON object")
    return {k: unwrap(v) for k, v in raw.items()}
