"""The visible source version and launcher match the shipped project metadata."""
import runpy
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest
from murmur import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_source_identity_matches_project_and_lockfile():
    project=tomllib.loads((ROOT/'pyproject.toml').read_text(encoding='utf-8'))
    locked=tomllib.loads((ROOT/'uv.lock').read_text(encoding='utf-8'))
    package=next(p for p in locked['package'] if p['name']=='murmur-desktop')
    assert project['project']['version']==package['version']==__version__


@pytest.mark.parametrize('code',[0,3])
def test_source_launcher_propagates_application_exit_code(monkeypatch,code):
    # Exercise the actual launcher without Qt, private profiles or device access.
    monkeypatch.setitem(sys.modules,'murmur.app',SimpleNamespace(main=lambda:code))
    with pytest.raises(SystemExit) as exit_result:
        runpy.run_path(str(ROOT/'run.py'),run_name='__main__')
    assert exit_result.value.code==code
