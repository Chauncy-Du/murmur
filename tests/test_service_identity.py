import pytest
from murmur.service_identity import model_source_label


@pytest.mark.parametrize('endpoint,label',[
    ('https://api.deepseek.com/v1','DeepSeek Official'),
    ('https://api.deepseek.com/','DeepSeek Official'),
    ('https://openclaw.icalculate.website/ai/v1','ProjectHub Private'),
    ('https://openclaw.icalculate.website/ai','ProjectHub Private'),
    ('http://127.0.0.1:11434/v1','Local'),
    ('http://[::1]:11434/v1','Local'),
    ('https://api.deepseek.com.evil.example/v1','Custom API · api.deepseek.com.evil.example'),
    ('https://private.example/deepseek/v1','Custom API · private.example'),
    ('http://api.deepseek.com/v1','Custom API · api.deepseek.com'),
    ('https://api.deepseek.com:8443/v1','Custom API · api.deepseek.com:8443'),
    ('','Custom API'),
    ('https://[broken','Custom API'),
])
def test_endpoint_origin_does_not_infer_official_service_from_model_name(endpoint,label):
    assert model_source_label(endpoint)==label


def test_display_does_not_expose_url_secrets():
    label=model_source_label('https://synthetic-user:synthetic-secret@private.example:8443/v1/hidden?token=private-key#private-fragment')
    assert label=='Custom API · private.example:8443'
    assert not any(secret in label for secret in ('synthetic','hidden','token','private-key','private-fragment'))
