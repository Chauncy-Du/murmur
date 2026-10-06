import io
import logging
from murmur.console import configure,event,banner,LOGO


def test_level_filter_color_and_safe_single_line(monkeypatch):
    output=io.StringIO();configure('INFO','always',output)
    event('speech','Ready')
    event('session','Hidden',level='DEBUG')
    event('services','bad\n\x1b[31m label',level='WARNING')
    value=output.getvalue()
    assert '\x1b[36m[info]' in value and '\x1b[33m[warning]' in value
    assert 'Hidden' not in value and len(value.splitlines())==2
    assert '\x1b[31m label' not in value
    configure('INFO','never')


def test_debug_and_redirected_output_are_plain(monkeypatch):
    output=io.StringIO();configure('DEBUG','auto',output)
    event('startup','Preparing',level='DEBUG')
    assert '[debug]' in output.getvalue() and '\x1b' not in output.getvalue()
    configure('INFO','never')


def test_no_color_and_dynamic_stdout(monkeypatch):
    class Terminal(io.StringIO):
        def isatty(self):return True
    output=Terminal();monkeypatch.setenv('NO_COLOR','1')
    monkeypatch.setattr('murmur.console._terminal_color',lambda stream:True)
    configure('INFO','auto');monkeypatch.setattr('sys.stdout',output)
    event('app','Ready')
    assert 'Ready' in output.getvalue() and '\x1b' not in output.getvalue()
    configure('INFO','never')


def test_process_tree_excludes_unrelated_processes():
    from murmur.process_resources import descendants
    assert descendants({2:1,3:2,4:9,5:3},1)=={1,2,3,5}


def test_logo_precedes_logs_and_is_not_filtered_by_level():
    output=io.StringIO();configure('ERROR','never',output)
    banner();event('app','Failed',level='ERROR')
    assert output.getvalue().startswith(LOGO+'\n\n')
    assert len(LOGO.splitlines())==11 and '[error]' in output.getvalue()
    assert LOGO.isascii() and '&#x20;' not in LOGO
    configure('INFO','never')


def test_gpu_memory_counts_only_selected_processes_and_distinguishes_unavailable():
    from murmur.process_resources import _Item,dedicated_bytes
    def item(pid,value,status=0):
        record=_Item();record.name=f'pid_{pid}_luid_0x1_phys_0';record.counter.value=value;record.counter.status=status;return record
    assert dedicated_bytes([item(1,100),item(2,50),item(3,9999)],{1,2})==150
    assert dedicated_bytes([item(3,9999)],{1,2})==0
    assert dedicated_bytes([item(1,100,0xC0000BC6)],{1}) is None
