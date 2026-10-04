"""Offline provider marks for model selectors; see docs/PROVIDER_ICONS.md.

An engine name is not a provider logo. Engines without a verified licensed
mark receive MurMur's neutral speech glyphs, and unknown models remain neutral.
"""
from __future__ import annotations

from pathlib import Path
import re

from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon


_ASSETS = Path(__file__).resolve().parent / 'assets' / 'providers'
_FILES = {
    'qwen': 'qwen.png',
    'deepseek': 'deepseek.svg',
    'openai': 'openai.svg',
    'ollama': 'ollama.svg',
    'sensevoice': 'sensevoice-neutral.svg',
    'paraformer': 'paraformer-neutral.svg',
    'funasr': 'funasr-neutral.svg',
    'cloud-speech': 'cloud-speech-neutral.svg',
    'speech': 'speech-neutral.svg',
    'local': 'local-neutral.svg',
    'model': 'model-neutral.svg',
}


def provider_icon_key(model_or_provider: str) -> str:
    """Resolve known model families without branding arbitrary API endpoints.

    Family names take precedence over serving runtimes: for example,
    ``Ollama / Qwen3:4b`` displays Qwen. An OpenAI-compatible transport alone
    does not establish that its configured model is from OpenAI.
    """
    value = re.sub(r'[_\s]+', '-', str(model_or_provider or '').strip().casefold())
    if 'deepseek' in value:
        return 'deepseek'
    if 'qwen' in value or 'qwq' in value:
        return 'qwen'
    if 'sensevoice' in value or 'sense-voice' in value:
        return 'sensevoice'
    if 'paraformer' in value:
        return 'paraformer'
    if 'funasr' in value or 'fun-asr' in value:
        return 'funasr'
    if re.search(r'(^|[/\s:-])gpt(?:[-\d:]|$)', value):
        return 'openai'
    if re.search(r'(^|[/\s:-])o[134](?:[-\d:]|$)', value):
        return 'openai'
    if 'openai' in value and 'compatible' not in value:
        return 'openai'
    if 'ollama' in value:
        return 'ollama'
    if any(name in value for name in ('bailian', 'dashscope', 'ali-nls', 'aliyun-nls')):
        return 'cloud-speech'
    if value in ('auto', 'auto-(local)', 'auto-local', 'local', 'local-model', 'automatic'):
        return 'local'
    if any(name in value for name in ('asr', 'speech', 'transcri', 'whisper', 'offline')):
        return 'speech'
    return 'model'


def provider_icon(model_or_provider: str, size: int = 20) -> QIcon:
    """Return a locally bundled icon; never inspect settings or use the network.

    Qt retains the original image source so SVG marks and the high resolution
    Qwen image can render cleanly at the caller's menu/icon size. This also
    works before QApplication creation because no QPixmap is allocated here.
    """
    if not isinstance(size, int) or isinstance(size, bool) or size < 1:
        raise ValueError('Provider icon size must be a positive integer.')
    path = _ASSETS / _FILES[provider_icon_key(model_or_provider)]
    if not path.is_file():
        # A missing optional brand asset should still leave model choice usable.
        path = _ASSETS / _FILES['model']
    icon = QIcon()
    icon.addFile(str(path), QSize(size, size))
    return icon


__all__ = ['provider_icon', 'provider_icon_key']
