import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
from PySide6.QtWidgets import QApplication
from murmur import storage, service_checks
from murmur.dashboard import MainWindow
from murmur.projecthub import BASE_URL


@pytest.fixture
def window(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    monkeypatch.setattr(storage,'credential',lambda *args:'')
    import sounddevice
    monkeypatch.setattr(sounddevice,'query_devices',lambda:[])
    store=storage.Store(tmp_path)
    widget=MainWindow(store)
    widget.navigate(3)
    widget.show()
    app.processEvents()
    yield widget
    widget.hide()
    store.db.close()


CATALOG=[{'id':'claude-opus-fixture','name':'Claude Opus Fixture'},
         {'id':'gemini-flash-fixture','name':'Gemini Flash Fixture'}]


def choose_private(window,kind):
    combo=window.services_model_choices[kind]
    combo.setCurrentIndex(combo.findData('projecthub'))


@pytest.mark.parametrize('kind,prefix',(('llm','llm'),('ask','ask_llm')))
def test_discovery_display_name_saves_id_and_overview_selection(window,kind,prefix):
    choose_private(window,kind)
    picker=window.fields[prefix+'_model']
    original=picker.text()
    window.set_service_model_metadata(kind,{'success':True,'model':original,'models':CATALOG})
    assert picker.text()==original  # No unrequested model change on refresh.
    picker.combo.setCurrentIndex(picker.combo.findData(CATALOG[0]['id']))
    assert picker.combo.currentText()==CATALOG[0]['name']
    assert window.service_test_values()[0][prefix+'_model']==CATALOG[0]['id']
    overview=window.services_model_choices[kind]
    assert overview.currentData()=='catalog:'+CATALOG[0]['id']
    overview.setCurrentIndex(overview.findData('catalog:'+CATALOG[1]['id']))
    assert picker.text()==CATALOG[1]['id']


@pytest.mark.parametrize('kind,prefix,attribute',(('llm','llm','llm_key'),('ask','ask_llm','ask_llm_key')))
def test_draft_key_refresh_without_model_and_no_save(window,kind,prefix,attribute):
    choose_private(window,kind)
    picker=window.fields[prefix+'_model']
    picker.setText('')
    getattr(window,attribute).setText('draft-key-only')
    requests=[]
    window.service_test.connect(lambda *args:requests.append(args))
    picker.refresh_button.click()
    assert len(requests)==1 and requests[0][0]==kind
    assert requests[0][1]['_model_discovery'] is True
    assert requests[0][2]['llm' if kind=='llm' else 'ask_llm']=='draft-key-only'
    assert requests[0][1][prefix+'_model']==''
    assert window.service_test_busy[kind] and not picker.refresh_button.isEnabled()
    assert not window.store.path.exists()


def test_key_edit_auto_refresh_and_stale_choices_cleared(window):
    choose_private(window,'llm')
    picker=window.fields['llm_model']
    picker.setModels(CATALOG)
    picker.combo.setCurrentIndex(picker.combo.findData(CATALOG[0]['id']))
    window.llm_key.setText('new-draft-key')
    assert not picker.models and picker.text()==CATALOG[0]['id']
    assert window.services_model_choices['llm'].findData('catalog:'+CATALOG[0]['id'])<0
    emitted=[]
    window.service_test.connect(lambda *args:emitted.append(args))
    window.llm_key.editingFinished.emit()
    assert len(emitted)==1 and emitted[0][1]['_model_discovery']
    window.set_service_test_state('llm',False)
    picker.setModels(CATALOG)
    window.fields['llm_url'].setText('https://other.fixture.invalid/v1')
    assert not picker.models


def test_failed_refresh_keeps_selected_id_and_custom_entry(window):
    choose_private(window,'ask')
    picker=window.fields['ask_llm_model']
    picker.setModels(CATALOG)
    picker.combo.setCurrentIndex(picker.combo.findData(CATALOG[0]['id']))
    window.set_service_test_state('ask',True)
    window.set_service_model_metadata('ask',{'success':False})
    window.set_service_test_state('ask',False,'Model discovery failed','HTTP 401',False)
    assert picker.text()==CATALOG[0]['id'] and picker.refresh_button.isEnabled()
    picker.combo.setEditText('custom-model-id')
    assert window.service_test_values()[0]['ask_llm_model']=='custom-model-id'


def test_controller_discards_catalog_for_changed_key(window):
    from types import SimpleNamespace
    from murmur.app import Controller
    choose_private(window,'llm')
    window.set_service_test_state('llm',True)
    fake=SimpleNamespace(quitting=False,window=window,
        service_tests={'llm':('request-one',None,'old-key-snapshot')},
        service_snapshot=lambda *args:'new-key-snapshot')
    Controller.service_checked(fake,'llm','request-one',
        {'success':True,'summary':'Models refreshed','model':'example','models':CATALOG})
    assert not window.fields['llm_model'].models
    assert window.service_test_results['llm'][0]=='Settings changed. Test again.'


def test_discovered_brand_marks_appear_in_picker_and_services(window):
    choose_private(window,'llm')
    models=[{'id':'gemini-3-6-flash','name':'Gemini 3.6 Flash'},
            {'id':'claude-opus-4-8','name':'Claude Opus 4.8'}]
    window.set_service_model_metadata('llm',{'success':True,'model':'gemini-3-6-flash','models':models})
    picker=window.fields['llm_model']
    overview=window.services_model_choices['llm']
    for model in models:
        index=picker.combo.findData(model['id'])
        assert not picker.combo.itemIcon(index).isNull()
        assert not overview.itemIcon(overview.findData('catalog:'+model['id'])).isNull()
