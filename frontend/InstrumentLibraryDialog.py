import sys
from PyQt5.QtWidgets import QDialog, QVBoxLayout
from PyQt5.QtCore import Qt 
from Translator import Translator
from LoadInstruments import LoadInstruments


class InstrumentLibraryDialog(QDialog):
    def __init__(self, load_instruments: LoadInstruments, parent=None, translator=None):
        super().__init__(parent)
        self.translator = translator
        self.load_instruments = load_instruments
        self.setWindowTitle(self.translator.tr("Instrument Library"))
        self.setGeometry(100, 100, 600, 400)

        self.layout = QVBoxLayout(self)
        self.setLayout(self.layout)

        self.init_ui()

    def init_ui(self):
        # Qui puoi usare self.load_instruments per popolare la UI
        pass

    def load_instrument_library(self):
        # Usa self.load_instruments per accedere ai dati
        return self.load_instruments

    def save_instrument_library(self):
        # Se serve salvare, usa i metodi di LoadInstruments
        pass