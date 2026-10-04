"""NLS CreateToken using the official POP HMAC-SHA1 POST protocol.

https://help.aliyun.com/zh/isi/user-guide/use-http-or-https-to-obtain-an-access-token
Credentials and the resulting token live exclusively in Windows Vault. Errors
never include response bodies, signed requests, credentials, or SDK exceptions.
"""
import base64
import hashlib
import hmac
import json
import threading
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import quote

import httpx
from .storage import credential, credential_lock

TOKEN_ENDPOINT = 'https://nls-meta.cn-shanghai.aliyuncs.com/'
REFRESH_MARGIN = 120
LOCK_WAIT_SECONDS = 10.0
REQUEST_DEADLINE_SECONDS = 15.0
MAX_RESPONSE_BYTES = 65536
_REFRESH_LOCK = threading.Lock()
_CREDENTIAL_NAMES = ('ali_access_key_id', 'ali_access_key_secret', 'ali_token', 'ali_token_expiry')
_SAFE_CODES = frozenset({
    'InvalidAccessKeyId.NotFound', 'SignatureDoesNotMatch', 'InvalidSignature',
    'MissingParameter', 'InvalidTimeStamp.Expired', 'Forbidden', 'Throttling',
    'ServiceUnavailable',
})


class AliAuthError(RuntimeError):
    """An intentionally sanitized user-visible authentication failure."""


def _check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise InterruptedError()


def _vault(name, value=None):
    try:
        return credential(name, value) if value is not None else credential(name)
    except Exception:
        raise AliAuthError('Alibaba credentials could not be accessed in Windows Credential Manager.') from None


def _encode(value):
    return quote(str(value), safe='-_.~')


def sign_parameters(parameters, secret, method='POST'):
    """Sign sorted, UTF-8 encoded parameters; exclude an existing Signature.

    This pure helper also supports the official GET fixture for regression
    validation. Actual token requests always use POST with form body fields.
    """
    canonical = '&'.join(_encode(key) + '=' + _encode(value)
                         for key, value in sorted(parameters.items())
                         if key != 'Signature')
    string_to_sign = method.upper() + '&%2F&' + _encode(canonical)
    signature = base64.b64encode(hmac.new(
        (secret + '&').encode('utf-8'), string_to_sign.encode('utf-8'),
        hashlib.sha1).digest()).decode('ascii')
    return canonical + '&Signature=' + _encode(signature)


def _request_token(access_key_id, secret, cancel):
    _check_cancel(cancel)
    parameters = {
        'AccessKeyId': access_key_id, 'Action': 'CreateToken',
        'Version': '2019-02-28', 'RegionId': 'cn-shanghai', 'Format': 'JSON',
        'SignatureMethod': 'HMAC-SHA1', 'SignatureVersion': '1.0',
        'SignatureNonce': str(uuid.uuid4()),
        'Timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    }
    deadline = time.monotonic() + REQUEST_DEADLINE_SECONDS
    try:
        # Bounded connect/read/write/pool waits and a bounded streamed body.
        # Cancellation is checked before/after each read, with no extra worker.
        with httpx.Client(timeout=httpx.Timeout(10, connect=5, write=5, pool=5),
                          follow_redirects=False) as client:
            with client.stream('POST', TOKEN_ENDPOINT,
                               content=sign_parameters(parameters, secret).encode('ascii'),
                               headers={'Content-Type': 'application/x-www-form-urlencoded',
                                        'Accept': 'application/json'}) as response:
                body = bytearray()
                for chunk in response.iter_bytes():
                    _check_cancel(cancel)
                    if time.monotonic() >= deadline:
                        raise AliAuthError('The Alibaba token request timed out. Try again.')
                    if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                        raise AliAuthError('Alibaba returned an invalid token response.')
                    body.extend(chunk)
                _check_cancel(cancel)
                try:
                    data = json.loads(body)
                except (ValueError, UnicodeError):
                    data = None
                if response.status_code != 200:
                    code = data.get('Code') if isinstance(data, dict) else None
                    suffix = ' (' + code + ')' if isinstance(code, str) and code in _SAFE_CODES else ''
                    raise AliAuthError('Alibaba token request failed' + suffix + '. Check AccessKey permissions and service availability.')
    except (InterruptedError, AliAuthError):
        raise
    except httpx.TimeoutException:
        _check_cancel(cancel)
        raise AliAuthError('The Alibaba token request timed out. Try again.') from None
    except Exception:
        _check_cancel(cancel)
        raise AliAuthError('Could not reach the Alibaba token service. Check your connection and try again.') from None
    token = data.get('Token') if isinstance(data, dict) else None
    identifier = token.get('Id') if isinstance(token, dict) else None
    expiry = token.get('ExpireTime') if isinstance(token, dict) else None
    if (not isinstance(identifier, str) or not identifier or len(identifier) > 8192 or
            any(character.isspace() or ord(character) < 32 for character in identifier) or
            isinstance(expiry, bool) or not isinstance(expiry, int) or
            expiry <= time.time() + REFRESH_MARGIN):
        raise AliAuthError('Alibaba returned an invalid or expired token response.')
    return identifier, expiry


def obtain_token(cancel=None, force=False):
    """Reuse a valid token or refresh from AK 120 seconds before expiry.

    Without a complete AK pair, a manually supplied token remains supported;
    an explicitly expired manual token fails before opening the microphone.
    Calls serialize refreshes and wait at most 10 seconds for a prior request.
    force=True requests a fresh token when a complete AK pair is available.
    """
    _check_cancel(cancel)
    deadline = time.monotonic() + LOCK_WAIT_SECONDS
    while not _REFRESH_LOCK.acquire(timeout=.05):
        _check_cancel(cancel)
        if time.monotonic() >= deadline:
            raise AliAuthError('A previous Alibaba token request is still finishing. Try again shortly.')
    try:
        _check_cancel(cancel)
        with credential_lock:
            snapshot = tuple(_vault(name) for name in _CREDENTIAL_NAMES)
        access_key_id, secret, cached, expiry_text = snapshot
        try:
            expiry = int(expiry_text) if expiry_text else None
        except (ValueError, TypeError):
            expiry = None
        now = time.time()
        _check_cancel(cancel)
        if not (access_key_id and secret):
            if cached and (expiry is None or expiry > now):
                return cached
            if cached:
                raise AliAuthError('The manual Alibaba NLS token has expired. Enter a new token or provide an AccessKey pair.')
            raise AliAuthError('Set an Alibaba NLS token or both AccessKey ID and AccessKey Secret in Settings.')
        # Unknown-expiry manual tokens are authoritative until forced refresh.
        if not force and cached and (expiry is None or expiry > now + REFRESH_MARGIN):
            return cached
        token, expiry = _request_token(access_key_id, secret, cancel)
        with credential_lock:
            _check_cancel(cancel)
            if tuple(_vault(name) for name in _CREDENTIAL_NAMES) != snapshot:
                raise AliAuthError('Credentials changed. Try again.')
            # The comparison and writes share the same lock as credential().
            # Network requests never hold this lock: saving or clearing keys
            # stays responsive and invalidates a late refresh instead.
            # Zero is expired, never "manual/unknown", if a write fails.
            _vault('ali_token_expiry', '0')
            _vault('ali_token', token)
            _vault('ali_token_expiry', str(expiry))
        return token
    finally:
        _REFRESH_LOCK.release()
