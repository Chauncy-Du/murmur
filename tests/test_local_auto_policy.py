"""Synthetic installed-model inventories; no downloads, server or user config."""
import copy
from itertools import permutations
import threading

import httpx
import pytest

from murmur.local_llm import resolve_model, LocalModelError


def cfg(**changes):
    result = dict(ollama=False, ollama_auto=True, llm_url='http://localhost:1234/v1',
                  llm_model='saved-explicit:2b')
    result.update(changes)
    return result


def selected(models, config=None, seen=None):
    config = cfg() if config is None else config

    def respond(request):
        if seen is not None:
            seen.append(request)
        assert request.method == 'GET' and not request.content
        return httpx.Response(200, json={'models' if config['ollama'] else 'data': models})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        return resolve_model(client, config)


def model(name, parameter_size=None, **metadata):
    result = dict(id=name, **metadata)
    if parameter_size is not None:
        result['details'] = dict(parameter_size=parameter_size)
    return result


@pytest.mark.parametrize('estimate,expected', [
    ('3.99B', 'small:2b'), ('4B', 'candidate'), ('4000M', 'candidate'),
    ('4.7B', 'candidate'), ('8B', 'candidate'), ('8000M', 'candidate'),
    ('8.01B', 'small:2b'),
])
def test_preferred_range_is_inclusive_and_based_on_parameter_estimate(estimate, expected):
    assert selected([model('candidate', estimate), model('small:2b')]) == expected


def test_smallest_within_band_wins_over_loaded_state_and_tiny_files():
    models = [model('small:2b', size=1, loaded=True),
              model('larger:8b', size=1, loaded=True),
              model('preferred:4b', size=9_000_000_000, loaded=False)]
    for order in permutations(models):
        assert selected(list(order)) == 'preferred:4b'


def test_reported_parameter_size_overrides_model_tag_and_top_level_is_supported():
    assert selected([model('nominal:4b', '9B'), model('actual:5b')]) == 'actual:5b'
    assert selected([model('nominal:2b', '4.7B'), model('actual:7b')]) == 'nominal:2b'
    assert selected([model('custom-local', parameter_size='4.5B'), model('small:2b')]) == 'custom-local'
    assert selected([dict(id='custom-local', parameter_size='5B'), model('small:2b')]) == 'custom-local'


@pytest.mark.parametrize('models,expected', [
    ([model('model:2b'), model('model:9b')], 'model:2b'),
    ([model('model:500m'), model('model:3b')], 'model:500m'),
    ([model('model:9b'), model('model:13b')], 'model:9b'),
    ([model('z-chat', loaded=True), model('a-chat')], 'a-chat'),
])
def test_no_band_retains_existing_small_model_or_deterministic_fallback(models, expected):
    assert selected(models) == expected
    assert selected(models[::-1]) == expected


@pytest.mark.parametrize('estimate', ['nanB', 'infB', '0B', '-4B', '4..7B', True, {}])
def test_invalid_parameter_metadata_cannot_manufacture_band_membership(estimate):
    assert selected([model('invalid-parameter', estimate), model('valid:6b')]) == 'valid:6b'


def test_cloud_and_nontext_candidates_cannot_win_preferred_band():
    models = [model('qwen:4b-cloud'), model('local-proxy:4b', remote_host='remote.invalid'),
              model('remote-alias:4b', remote_model='remote-name'),
              model('embed:4b'), model('bert:4b'), model('reranker:4b'),
              model('safe:2b')]
    assert selected(models) == 'safe:2b'


@pytest.mark.parametrize('ollama', [False, True])
def test_both_protocols_use_fresh_inventory_without_mutating_config(ollama):
    config = cfg(ollama=ollama)
    original = copy.deepcopy(config)
    seen = []
    first = [dict(name='first:4b', details=dict(parameter_size='4B'))] if ollama else [model('first:4b')]
    second = [dict(name='second:6b', details=dict(parameter_size='6B'))] if ollama else [model('second:6b')]
    assert selected(first, config, seen) == 'first:4b'
    assert selected(second, config, seen) == 'second:6b'
    assert config == original
    assert len(seen) == 2 and all(r.headers['Authorization'] == 'Bearer local' for r in seen)
    assert all(r.url.path == ('/api/tags' if ollama else '/v1/models') for r in seen)


@pytest.mark.parametrize('name', ['exact-custom-alias', 'selected:2b', 'selected:9b'])
def test_named_selection_remains_exact_without_inventory_probe(name):
    with httpx.Client(transport=httpx.MockTransport(lambda request: pytest.fail('Named model requested inventory'))) as client:
        assert resolve_model(client, cfg(ollama_auto=False, llm_model=name)) == name


def test_cancelled_and_empty_inventory_do_not_select_a_fallback():
    cancel = threading.Event(); cancel.set()
    with httpx.Client(transport=httpx.MockTransport(lambda request: pytest.fail('Cancelled request reached server'))) as client:
        with pytest.raises(InterruptedError):
            resolve_model(client, cfg(), cancel)
    with pytest.raises(LocalModelError, match='No installed local text model'):
        selected([model('cloud:4b-cloud')])
