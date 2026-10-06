import httpx
import pytest
from murmur.release_check import stable_version,select_release,check_releases,API_URL


def release(tag,**flags):return dict(tag_name=tag,prerelease=False,draft=False,**flags) if not flags else {'tag_name':tag,'prerelease':False,'draft':False,**flags}


@pytest.mark.parametrize('tag',['0.0.99','v0.0.999','v0.8.0-beta','0.8.0rc1','1.0.0','garbage',None])
def test_beta_and_other_series_are_excluded(tag):assert stable_version(tag) is None


def test_highest_numeric_stable_release_wins_over_date_or_order():
    items=[release('v0.9.99'),release('v0.10.2'),release('v0.0.9999'),release('v0.20.0',prerelease=True),release('v0.30.0',draft=True)]
    result=select_release(items,'0.4.6')
    assert result.state=='update' and result.latest=='0.10.2'
    assert result.url.endswith('/releases/tag/v0.10.2')


def test_empty_does_not_claim_up_to_date():
    assert select_release([],'0.4.6').state=='empty'
    assert select_release([release('v0.0.9')],'0.4.6').state=='empty'
    assert select_release([release('v0.4.6')],'0.4.6').state=='current'
    assert select_release([release('v0.4.5')],'0.4.6').state=='ahead'


def test_pagination_finds_stable_release_after_beta_page():
    seen=[]
    def handler(request):
        seen.append(request.url.params['page'])
        assert str(request.url).startswith(API_URL) and 'authorization' not in request.headers
        return httpx.Response(200,json=[release('0.0.1')]*100 if len(seen)==1 else [release('v0.5.0')])
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert check_releases('0.4.6',client).latest=='0.5.0'
    assert seen==['1','2']


@pytest.mark.parametrize('status,body',[(403,{}),(429,{}),(404,{}),(500,{}),(200,{'message':'bad'})])
def test_http_and_shape_failures_are_not_success(status,body):
    with httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(status,json=body))) as client:
        assert check_releases('0.4.6',client).state=='error'


def test_timeout_returns_retryable_state():
    def handler(request):raise httpx.ReadTimeout('fixture')
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert check_releases('0.4.6',client).state=='error'
