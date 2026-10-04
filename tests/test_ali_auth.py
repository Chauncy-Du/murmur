"""NLS signing, refresh ownership, cancellation and safe errors; no real keys."""
import base64
import hashlib
import hmac
import threading
from urllib.parse import parse_qs, quote

import httpx
import pytest
from murmur import ali_auth


@pytest.fixture
def auth(monkeypatch):
    vault = {'ali_access_key_id':'fixture-id', 'ali_access_key_secret':'fixture-secret'}
    calls = []
    writes = []
    lock = threading.Lock()
    monkeypatch.setattr(ali_auth, '_REFRESH_LOCK', lock)
    monkeypatch.setattr(ali_auth.time, 'time', lambda:2000000000)
    def credential(name, value=None):
        if value is not None:
            writes.append((name, value))
            vault[name] = value
        return vault.get(name, '')
    monkeypatch.setattr(ali_auth, 'credential', credential)
    real_client = httpx.Client
    def install(handler=None):
        def respond(request):
            calls.append(request)
            return handler(request) if handler else httpx.Response(
                200, json={'Token':{'Id':'fixture-new-token', 'ExpireTime':2000003600}})
        def client(**kwargs):
            assert kwargs['timeout'].connect == 5 and kwargs['timeout'].read == 10
            assert kwargs['follow_redirects'] is False
            return real_client(transport=httpx.MockTransport(respond), **kwargs)
        monkeypatch.setattr(ali_auth.httpx, 'Client', client)
    install()
    return vault, calls, writes, install, lock


def official_fixture():
    return {
        'AccessKeyId':'my_access_key_id', 'Action':'CreateToken', 'Format':'JSON',
        'RegionId':'cn-shanghai', 'SignatureMethod':'HMAC-SHA1',
        'SignatureNonce':'b924c8c3-6d03-4c5d-ad36-d984d3116788',
        'SignatureVersion':'1.0', 'Timestamp':'2019-04-18T08:32:31Z',
        'Version':'2019-02-28',
    }


def test_official_get_signature_fixture_and_post_method():
    parameters = official_fixture()
    get = ali_auth.sign_parameters(parameters, 'my_access_key_secret', 'GET')
    assert get.endswith('&Signature=hHq4yNsPitlfDJ2L0nQPdugdEzM%3D')
    post = ali_auth.sign_parameters(parameters, 'my_access_key_secret')
    canonical = get.split('&Signature=')[0]
    expected = base64.b64encode(hmac.new(b'my_access_key_secret&',
        ('POST&%2F&' + quote(canonical, safe='-_.~')).encode(), hashlib.sha1).digest()).decode()
    assert parse_qs(post)['Signature'] == [expected]
    assert post != get
    parameters['Signature'] = 'ignored-old-signature'
    assert ali_auth.sign_parameters(parameters, 'my_access_key_secret') == post


def test_percent_encoding_uses_utf8_space_not_plus():
    signed = ali_auth.sign_parameters({'Test':'a b*~中/+'}, 'fixture-secret')
    assert signed.startswith('Test=a%20b%2A~%E4%B8%AD%2F%2B&Signature=')
    assert '+' not in signed


def test_create_token_posts_form_body_and_persists_only_to_vault(auth):
    vault, calls, writes, _, _ = auth
    assert ali_auth.obtain_token(force=True) == 'fixture-new-token'
    request = calls[0]
    assert request.method == 'POST' and str(request.url) == ali_auth.TOKEN_ENDPOINT
    assert request.headers['Content-Type'] == 'application/x-www-form-urlencoded'
    params = parse_qs(request.content.decode('ascii'))
    assert params['Action'] == ['CreateToken'] and params['RegionId'] == ['cn-shanghai']
    assert params['Version'] == ['2019-02-28'] and params['SignatureMethod'] == ['HMAC-SHA1']
    assert params['Timestamp'][0].endswith('Z') and params['SignatureNonce'][0]
    assert 'fixture-secret' not in request.content.decode('ascii')
    assert vault['ali_token'] == 'fixture-new-token' and vault['ali_token_expiry'] == '2000003600'
    assert [name for name, _ in writes] == ['ali_token_expiry', 'ali_token', 'ali_token_expiry']


@pytest.mark.parametrize('expiry,refreshed', [('2000000121', False), ('2000000120', True), ('1999999999', True)])
def test_cached_expiry_and_120_second_margin(auth, expiry, refreshed):
    vault, calls, _, _, _ = auth
    vault.update(ali_token='fixture-cached', ali_token_expiry=expiry)
    assert ali_auth.obtain_token() == ('fixture-new-token' if refreshed else 'fixture-cached')
    assert bool(calls) is refreshed


def test_manual_unknown_expiry_respected_until_forced(auth):
    vault, calls, _, _, _ = auth
    vault['ali_token'] = 'fixture-manual'
    assert ali_auth.obtain_token() == 'fixture-manual' and not calls
    assert ali_auth.obtain_token(force=True) == 'fixture-new-token' and len(calls) == 1


def test_manual_token_without_access_key_and_expired_rejection(auth):
    vault, calls, _, _, _ = auth
    vault.clear();vault['ali_token'] = 'fixture-manual'
    assert ali_auth.obtain_token(force=True) == 'fixture-manual' and not calls
    vault['ali_token_expiry'] = '2000000010'
    assert ali_auth.obtain_token() == 'fixture-manual'
    vault['ali_token_expiry'] = '1999999999'
    with pytest.raises(ali_auth.AliAuthError, match='manual.*expired'):
        ali_auth.obtain_token()
    assert not calls


def test_missing_credentials_does_not_request(auth):
    vault, calls, _, _, _ = auth
    vault.clear()
    with pytest.raises(ali_auth.AliAuthError, match='both AccessKey ID'):
        ali_auth.obtain_token()
    assert not calls


def test_cancellation_before_and_during_response_never_persists(auth):
    vault, calls, writes, install, _ = auth
    cancel = threading.Event();cancel.set()
    with pytest.raises(InterruptedError):ali_auth.obtain_token(cancel)
    assert not calls and not writes
    cancel.clear()
    def response(request):
        cancel.set()
        return httpx.Response(200, json={'Token':{'Id':'do-not-cache', 'ExpireTime':2000003600}})
    install(response)
    with pytest.raises(InterruptedError):ali_auth.obtain_token(cancel, force=True)
    assert not writes and not vault.get('ali_token')


def test_refresh_lock_cancel_and_finite_wait(auth, monkeypatch):
    _, calls, _, _, lock = auth
    lock.acquire()
    monkeypatch.setattr(ali_auth, 'LOCK_WAIT_SECONDS', .01)
    try:
        with pytest.raises(ali_auth.AliAuthError, match='previous Alibaba token request'):
            ali_auth.obtain_token()
        cancel = threading.Event()
        timer = threading.Timer(.01, cancel.set);timer.start()
        with pytest.raises(InterruptedError):ali_auth.obtain_token(cancel)
        timer.join()
    finally:lock.release()
    assert not calls


def test_simultaneous_refreshes_reuse_first_result(auth):
    _, calls, _, install, _ = auth
    entered = threading.Event();release = threading.Event();results = []
    def response(request):
        entered.set();assert release.wait(2)
        return httpx.Response(200, json={'Token':{'Id':'fixture-shared', 'ExpireTime':2000003600}})
    install(response)
    first = threading.Thread(target=lambda:results.append(ali_auth.obtain_token()))
    second = threading.Thread(target=lambda:results.append(ali_auth.obtain_token()))
    first.start();assert entered.wait(2);second.start();release.set()
    first.join(2);second.join(2)
    assert results == ['fixture-shared', 'fixture-shared'] and len(calls) == 1


@pytest.mark.parametrize('code,shown', [('InvalidAccessKeyId.NotFound', True), ('fixture-secret', False)])
def test_only_exact_error_code_whitelist_is_shown(auth, code, shown):
    _, _, writes, install, _ = auth
    install(lambda request:httpx.Response(403, json={
        'Code':code, 'Message':'fixture-secret token=fixture-new-token',
        'RequestId':'fixture-id'}))
    with pytest.raises(ali_auth.AliAuthError) as caught:ali_auth.obtain_token(force=True)
    message = str(caught.value)
    assert ('InvalidAccessKeyId.NotFound' in message) is shown
    assert 'fixture-secret' not in message and 'fixture-new-token' not in message
    assert 'fixture-id' not in message and not writes


@pytest.mark.parametrize('payload', [None, {}, {'Token':{}},
    {'Token':{'Id':'', 'ExpireTime':2000003600}},
    {'Token':{'Id':'fixture-token', 'ExpireTime':1999999999}},
    {'Token':{'Id':'fixture-token', 'ExpireTime':True}},
    {'Token':{'Id':'fixture-token', 'ExpireTime':'2000003600'}},
    {'Token':{'Id':'bad\nheader', 'ExpireTime':2000003600}}])
def test_invalid_response_never_enters_cache(auth, payload):
    _, _, writes, install, _ = auth
    install(lambda request:httpx.Response(200, json=payload))
    with pytest.raises(ali_auth.AliAuthError, match='invalid or expired token response'):
        ali_auth.obtain_token(force=True)
    assert not writes


def test_malformed_or_oversized_response_is_safe(auth):
    _, _, writes, install, _ = auth
    for body in (b'fixture-secret not JSON', b'x' * 65537):
        install(lambda request:httpx.Response(200, content=body))
        with pytest.raises(ali_auth.AliAuthError) as caught:ali_auth.obtain_token(force=True)
        assert 'fixture-secret' not in str(caught.value)
    assert not writes


@pytest.mark.parametrize('exception', [httpx.ReadTimeout, RuntimeError])
def test_http_and_sdk_exceptions_are_redacted(auth, exception):
    _, _, writes, install, _ = auth
    def fail(request):raise exception('fixture-secret signed-body fixture-new-token')
    install(fail)
    with pytest.raises(ali_auth.AliAuthError) as caught:ali_auth.obtain_token(force=True)
    assert 'fixture-secret' not in str(caught.value) and 'fixture-new-token' not in str(caught.value)
    assert not writes


@pytest.mark.parametrize('failure', ['token', 'expiry'])
def test_failed_vault_write_cannot_pair_old_token_with_new_expiry(auth, monkeypatch, failure):
    vault, calls, _, _, _ = auth
    vault.update(ali_token='fixture-old-token', ali_token_expiry='1999999999')
    original = ali_auth.credential
    def fail(name, value=None):
        if ((failure == 'token' and name == 'ali_token' and value is not None) or
                (failure == 'expiry' and name == 'ali_token_expiry' and value == '2000003600')):
            raise RuntimeError('secret Vault exception')
        return original(name, value)
    monkeypatch.setattr(ali_auth, 'credential', fail)
    with pytest.raises(ali_auth.AliAuthError, match='Credential Manager'):
        ali_auth.obtain_token(force=True)
    assert vault['ali_token'] == ('fixture-old-token' if failure == 'token' else 'fixture-new-token')
    assert vault['ali_token_expiry'] == '0'
    monkeypatch.setattr(ali_auth, 'credential', original)
    assert ali_auth.obtain_token() == 'fixture-new-token'
    assert len(calls) == 2 and vault['ali_token_expiry'] == '2000003600'


@pytest.mark.parametrize('change', ['manual_token', 'remove_credentials', 'replace_access_key'])
def test_late_refresh_never_overwrites_credentials_changed_during_http(auth, change):
    vault, _, writes, install, _ = auth
    entered = threading.Event();release = threading.Event();errors = []
    vault.update(ali_token='fixture-old', ali_token_expiry='0')
    def response(request):
        entered.set();assert release.wait(2)
        return httpx.Response(200, json={'Token':{'Id':'stale-network-token', 'ExpireTime':2000003600}})
    install(response)
    def refresh():
        try:ali_auth.obtain_token()
        except ali_auth.AliAuthError as exc:errors.append(str(exc))
    worker = threading.Thread(target=refresh)
    worker.start();assert entered.wait(2)
    # A real second thread changes the fake Vault while HTTP is in flight.
    # Its lock is the same shared lock used by production credential().
    def edit():
        with ali_auth.credential_lock:
            if change == 'manual_token':
                vault.update(ali_token='fixture-user-token', ali_token_expiry='')
            elif change == 'remove_credentials':vault.clear()
            else:vault.update(ali_access_key_id='fixture-new-id', ali_access_key_secret='fixture-new-secret')
    writer = threading.Thread(target=edit);writer.start();writer.join(2)
    assert not writer.is_alive()  # HTTP never blocks a user's credential change.
    expected = vault.copy();release.set();worker.join(2)
    assert not worker.is_alive() and errors == ['Credentials changed. Try again.']
    assert vault == expected and writes == []


def test_snapshot_comparison_and_token_commit_hold_one_shared_lock(auth, monkeypatch):
    vault, _, _, _, _ = auth
    committing = threading.Event();attempted = threading.Event();changed = threading.Event()
    original = ali_auth.credential;results = []
    def credential(name, value=None):
        if name == 'ali_token_expiry' and value == '0':
            committing.set();assert attempted.wait(2)
            assert not changed.wait(.05), 'Writer slipped between snapshot comparison and commit'
        return original(name, value)
    monkeypatch.setattr(ali_auth, 'credential', credential)
    def writer():
        assert committing.wait(2)
        attempted.set()
        with ali_auth.credential_lock:
            vault.update(ali_token='fixture-later-user-token', ali_token_expiry='')
            changed.set()
    second = threading.Thread(target=writer);second.start()
    results.append(ali_auth.obtain_token(force=True));second.join(2)
    assert changed.is_set() and results == ['fixture-new-token']
    assert vault['ali_token'] == 'fixture-later-user-token' and vault['ali_token_expiry'] == ''
