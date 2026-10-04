"""Model marks are local, correctly attributed, and render visibly in Qt."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from murmur.provider_icons import provider_icon, provider_icon_key


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize(('model', 'key'), [
    ('qwen3.5:4b', 'qwen'), ('Qwen3-ASR 1.7B', 'qwen'),
    ('Ollama / Qwen3:4b', 'qwen'), ('qwen_asr', 'qwen'),
    ('SenseVoice Small', 'sensevoice'), ('sensevoice', 'sensevoice'),
    ('Paraformer INT8', 'paraformer'), ('fun_asr_nano', 'funasr'),
    ('FunASR', 'funasr'), ('bailian', 'cloud-speech'), ('ali_nls', 'cloud-speech'),
    ('deepseek-chat', 'deepseek'), ('DeepSeek-R1:8b', 'deepseek'),
    ('OpenAI', 'openai'), ('gpt-4.1-mini', 'openai'), ('gpt-oss:20b', 'openai'),
    ('Ollama', 'ollama'), ('auto (local)', 'local'), ('auto', 'local'),
    ('Unspecified speech engine', 'speech'), ('offline', 'speech'),
    ('OpenAI-compatible', 'model'), ('my-custom-model', 'model'), ('', 'model'),
])
def test_model_and_provider_identity(model, key):
    assert provider_icon_key(model) == key


@pytest.mark.parametrize('key', [
    'qwen', 'deepseek', 'openai', 'ollama', 'sensevoice', 'paraformer',
    'funasr', 'ali_nls', 'speech', 'local', 'unknown-model',
])
def test_bundled_icons_are_visibly_rendered_without_network(app, key, monkeypatch):
    import socket
    monkeypatch.setattr(socket, 'create_connection', lambda *a, **k: pytest.fail('Icon used network'))
    icon = provider_icon(key)
    assert not icon.isNull()
    pixmap = icon.pixmap(QSize(20, 20))
    assert not pixmap.isNull()
    image = pixmap.toImage()
    # Catch both transparent SVGs and white-only official assets that Qt parses
    # successfully but cannot paint, e.g. unsupported CSS variables.
    visible = sum(
        image.pixelColor(x, y).alpha() > 0
        and min(image.pixelColor(x, y).red(), image.pixelColor(x, y).green(), image.pixelColor(x, y).blue()) < 220
        for x in range(image.width()) for y in range(image.height())
    )
    assert visible >= 8, key


def test_assets_are_self_contained_and_attribution_is_bundled():
    assets = Path(__file__).resolve().parents[1] / 'murmur' / 'assets' / 'providers'
    for name in ('deepseek', 'ollama', 'qwen'):
        assert (assets / f'LICENSE.{name}.txt').is_file()
    for asset in assets.glob('*.svg'):
        root = ET.fromstring(asset.read_bytes())
        for element in root.iter():
            assert not element.tag.endswith(('script', 'image', 'foreignObject'))
            for value in element.attrib.values():
                assert not value.startswith(('http:', 'https:', 'file:', 'data:'))
    assert (assets / 'deepseek-source.svg').is_file()
    assert (assets / 'openai-source.svg').is_file()
    assert (assets / 'ollama-source.svg').is_file()


def test_icons_remain_visible_on_actual_dark_surfaces(app):
    def luminance(color):
        channels = (color.redF(), color.greenF(), color.blueF())
        linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in channels]
        return sum(value * weight for value, weight in zip(linear, (0.2126, 0.7152, 0.0722)))

    for background in ('#242428', '#252429'):
        base = QColor(background)
        base_luminance = luminance(base)
        for key in ('qwen', 'deepseek', 'openai', 'ollama', 'sensevoice', 'paraformer', 'funasr', 'ali_nls', 'speech', 'local', 'custom'):
            image = QImage(20, 20, QImage.Format.Format_ARGB32)
            image.fill(base)
            pixmap = provider_icon(key).pixmap(QSize(20, 20))
            painter = QPainter(image)
            painter.drawPixmap((20 - pixmap.width()) // 2, (20 - pixmap.height()) // 2, pixmap)
            painter.end()
            visible = sum(
                (luminance(image.pixelColor(x, y)) + 0.05) / (base_luminance + 0.05) >= 3
                for x in range(20) for y in range(20)
            )
            assert visible >= 8, (key, background)


def test_ollama_display_badge_preserves_the_original_black_mark():
    assets = Path(__file__).resolve().parents[1] / 'murmur' / 'assets' / 'providers'
    source = ET.fromstring((assets / 'ollama-source.svg').read_bytes())
    display = ET.fromstring((assets / 'ollama.svg').read_bytes())
    tag = '{http://www.w3.org/2000/svg}path'
    assert [path.attrib for path in source.iter(tag)] == [path.attrib for path in display.iter(tag)]


@pytest.mark.parametrize('size', [0, -1, 20.5, True])
def test_invalid_icon_size_is_rejected(size):
    with pytest.raises(ValueError):
        provider_icon('qwen', size=size)
