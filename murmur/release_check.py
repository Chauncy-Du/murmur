"""Read-only stable 0.x GitHub Release checks; tags are not releases."""
from dataclasses import dataclass
import re
import httpx

REPOSITORY='Chauncy-Du/murmur'
RELEASES_URL=f'https://github.com/{REPOSITORY}/releases'
API_URL=f'https://api.github.com/repos/{REPOSITORY}/releases'


def stable_version(tag):
    if not isinstance(tag,str):return None
    match=re.fullmatch(r'v?0\.(\d+)(?:\.(\d+))?',tag)
    if not match or int(match[1])==0:return None
    return (0,int(match[1]),int(match[2] or 0))


@dataclass(frozen=True)
class ReleaseStatus:
    state:str
    message:str
    latest:str=''
    url:str=RELEASES_URL


def select_release(releases,current):
    candidates=[]
    for release in releases:
        if not isinstance(release,dict) or release.get('draft') or release.get('prerelease'):continue
        version=stable_version(release.get('tag_name'))
        if version:candidates.append((version,release['tag_name']))
    if not candidates:return ReleaseStatus('empty','No stable Release published')
    version,tag=max(candidates)
    installed=stable_version(current)
    url=RELEASES_URL+'/tag/'+tag
    latest=tag.removeprefix('v')
    if installed is None:return ReleaseStatus('unknown',f'Latest stable: {latest}',latest,url)
    if version>installed:return ReleaseStatus('update',f'Update available · {latest}',latest,url)
    if version==installed:return ReleaseStatus('current',f'Up to date · {latest}',latest,url)
    return ReleaseStatus('ahead',f'Local version ahead of {latest}',latest,url)


def check_releases(current,client=None):
    def fetch(session):
        releases=[]
        for page in range(1,11):
            response=session.get(API_URL,params={'per_page':100,'page':page},
                                 headers={'Accept':'application/vnd.github+json','User-Agent':'MurMur-release-check'})
            if response.status_code in (403,429):return ReleaseStatus('error','GitHub limit reached · Try later')
            if response.status_code==404:return ReleaseStatus('error','Repository unavailable')
            response.raise_for_status();batch=response.json()
            if not isinstance(batch,list):return ReleaseStatus('error','Invalid release response')
            releases.extend(batch)
            if len(batch)<100:return select_release(releases,current)
        return ReleaseStatus('error','Release list incomplete · View GitHub')
    try:
        if client is not None:return fetch(client)
        with httpx.Client(timeout=8.,follow_redirects=False) as session:return fetch(session)
    except (httpx.HTTPError,ValueError,TypeError):
        return ReleaseStatus('error','Could not check · Try again')
