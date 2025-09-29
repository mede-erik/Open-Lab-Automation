import sys
from PyQt5.QtWidgets import QDialog, QVBoxLayout
from PyQt5.QtCore import Qt
from Translator import Translator


class HexDecConverterDialog(QDialog):   
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Hex/Dec Converter")
        self.setGeometry(100, 100, 400, 300)

        self.layout = QVBoxLayout(self)
        self.setLayout(self.layout)

        self.init_ui()

    def init_ui(self):
        # Initialize UI components here
        pass

    def convert_hex_to_dec(self, hex_value):
        # Convert hex to decimal
        pass

    def convert_dec_to_hex(self, dec_value):
        # Convert decimal to hex
        pass