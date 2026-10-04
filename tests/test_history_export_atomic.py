"""Export transactions use synthetic records and never read user history."""
import csv
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from murmur.dashboard import MainWindow, QFileDialog, QMessageBox


@pytest.fixture
def export_fixture(tmp_path, monkeypatch):
    rows = [{'time': '2026-01-01T12:00:00', 'mode': '听写', 'raw': 'Fixture 原文',
             'final': 'Fixture result, with comma\nand newline', 'context': ''}]
    window = SimpleNamespace(current_rows=rows)
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args[1:]))

    def export(name):
        destination = tmp_path / name
        monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(destination), ''))
        MainWindow.export_history(window)
        return destination

    return window, warnings, export


@pytest.mark.parametrize('name', ['sessions.json', 'sessions.CSV'])
def test_export_preserves_filtered_schema_and_replaces_only_complete_file(export_fixture, tmp_path, monkeypatch, name):
    window, warnings, export = export_fixture
    destination = tmp_path / name
    destination.write_bytes(b'Previous export')
    replace = os.replace
    observations = []

    def verify_then_replace(source, target):
        source, target = Path(source), Path(target)
        assert source.parent == destination.parent
        assert target == destination and target.read_bytes() == b'Previous export'
        data = source.read_bytes()
        if name.lower().endswith('.csv'):
            assert data.startswith(b'\xef\xbb\xbf')
            with source.open(encoding='utf-8-sig', newline='') as f:
                assert list(csv.DictReader(f)) == window.current_rows
        else:
            assert json.loads(data.decode('utf-8')) == window.current_rows
        observations.append(True)
        replace(source, target)

    monkeypatch.setattr(os, 'replace', verify_then_replace)
    assert export(name) == destination
    assert observations == [True] and not warnings
    assert list(tmp_path.iterdir()) == [destination]


def test_partial_csv_write_failure_keeps_previous_export_and_cleans_temporary(export_fixture, tmp_path, monkeypatch):
    window, warnings, export = export_fixture
    destination = tmp_path / 'sessions.csv'
    destination.write_bytes(b'Previous export')
    window.current_rows *= 2
    original = csv.DictWriter

    class FailedWriter(original):
        def writerows(self, rows):
            self.writerow(rows[0])  # A meaningful mid-write failure, after real bytes.
            raise OSError('fixture-sensitive-system-detail')

    monkeypatch.setattr(csv, 'DictWriter', FailedWriter)
    export(destination.name)
    assert destination.read_bytes() == b'Previous export'
    assert list(tmp_path.iterdir()) == [destination]
    assert warnings[0][0] == 'Export failed'
    assert 'previous export is unchanged' in warnings[0][1]
    assert 'fixture-sensitive' not in warnings[0][1]


@pytest.mark.parametrize('operation', ['fsync', 'replace'])
def test_flush_or_replace_failure_preserves_previous_export(export_fixture, tmp_path, monkeypatch, operation):
    _, warnings, export = export_fixture
    destination = tmp_path / 'sessions.json'
    destination.write_bytes(b'Previous export')

    def fail(*args):
        raise PermissionError('fixture-only locked destination')

    monkeypatch.setattr(os, operation, fail)
    export(destination.name)
    assert destination.read_bytes() == b'Previous export'
    assert len(warnings) == 1 and list(tmp_path.iterdir()) == [destination]


def test_empty_csv_keeps_existing_header_schema(export_fixture):
    window, warnings, export = export_fixture
    window.current_rows = []
    destination = export('empty.csv')
    with destination.open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == ['time', 'mode', 'raw', 'final', 'context']
        assert list(reader) == []
    assert not warnings


def test_cancelled_dialog_does_not_write_or_show_warning(export_fixture, tmp_path, monkeypatch):
    window, warnings, _ = export_fixture
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: ('', ''))
    MainWindow.export_history(window)
    assert not warnings and not list(tmp_path.iterdir())


def test_temp_creation_failure_shows_safe_error(export_fixture, tmp_path):
    _, warnings, export = export_fixture
    export('missing-directory/sessions.json')
    assert len(warnings) == 1
    assert not list(tmp_path.iterdir())
