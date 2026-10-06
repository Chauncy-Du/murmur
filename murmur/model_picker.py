"""A model selector that exposes stable IDs to existing settings code."""
from PySide6.QtCore import Signal, QSignalBlocker, Qt, QSize
from PySide6.QtWidgets import QWidget, QVBoxLayout
from .ui import CompactComboBox, button
from .provider_icons import provider_icon


class ModelPicker(QWidget):
    textChanged = Signal(str)
    refreshRequested = Signal()
    modelsChanged = Signal()

    def __init__(self, value=''):
        super().__init__()
        self.models = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(5)
        self.combo = CompactComboBox()
        self.combo.setEditable(True)
        self.combo.setIconSize(QSize(18,18))
        self.combo.setInsertPolicy(self.combo.InsertPolicy.NoInsert)
        self.combo.setMinimumWidth(0)
        self.combo.setAccessibleName('Text model')
        self.combo.setToolTip('Choose a discovered model. Custom model IDs can still be entered.')
        self.refresh_button = button('Refresh models',self.refreshRequested.emit)
        self.refresh_button.setAccessibleName('Refresh available text models')
        self.refresh_button.setToolTip('Fetch available models using the API URL and key currently entered. No generation is submitted.')
        layout.addWidget(self.combo)
        layout.addWidget(self.refresh_button)
        self.setText(value)
        self.combo.currentTextChanged.connect(lambda _:self.textChanged.emit(self.text()))

    def text(self):
        index = self.combo.currentIndex()
        if index>=0 and self.combo.currentText()==self.combo.itemText(index):
            return self.combo.itemData(index) or ''
        return self.combo.currentText()

    def setText(self, value):
        before=self.text()
        with QSignalBlocker(self.combo):
            index=self.combo.findData(value)
            if index<0:
                self.combo.addItem(provider_icon(value,18),value,value)
                index=self.combo.count()-1
            self.combo.setCurrentIndex(index)
        if before!=self.text():self.textChanged.emit(self.text())

    def setModels(self, models):
        current=self.text()
        self.models=list(models)
        with QSignalBlocker(self.combo):
            self.combo.clear()
            for item in self.models:
                identity=item['id'];name=item.get('name') or identity
                self.combo.addItem(provider_icon(identity+' / '+name,18),name,identity)
                self.combo.setItemData(self.combo.count()-1,identity,Qt.ToolTipRole)
            index=self.combo.findData(current)
            if index<0:
                # Refresh never silently changes a saved model or its endpoint.
                self.combo.insertItem(0,provider_icon(current,18),current or 'Select a model…',current)
                index=0
            self.combo.setCurrentIndex(index)
        self.modelsChanged.emit()

    def clearModels(self):
        self.setModels([])
