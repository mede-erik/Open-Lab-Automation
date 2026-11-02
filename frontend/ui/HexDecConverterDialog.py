from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QFormLayout, QLineEdit, QLabel
from frontend.core.Translator import Translator


def parse_int(text, base):
    """
    Converte una stringa in intero nella base indicata (16, 10 o 2).
    Accetta spazi, underscore e prefissi 0x/0b e segno meno.
    Solleva ValueError se la stringa non e' valida.
    """
    cleaned = text.strip().replace(' ', '').replace('_', '')
    if not cleaned:
        raise ValueError("empty")
    negative = cleaned.startswith('-')
    if negative:
        cleaned = cleaned[1:]
    prefix = {16: '0x', 2: '0b'}.get(base)
    if prefix and cleaned.lower().startswith(prefix):
        cleaned = cleaned[len(prefix):]
    if not cleaned or cleaned[0] in '+-':
        raise ValueError("invalid")
    value = int(cleaned, base)
    return -value if negative else value


def format_hex(value):
    return f"-0x{-value:X}" if value < 0 else f"0x{value:X}"


def format_bin(value):
    return f"-0b{bin(-value)[2:]}" if value < 0 else f"0b{bin(value)[2:]}"


class HexDecConverterDialog(QDialog):
    """Convertitore bidirezionale tra esadecimale, decimale e binario."""

    def __init__(self, parent=None, translator=None):
        super().__init__(parent)
        self.translator = translator or getattr(parent, 'translator', None) or self._default_translator()
        title = self.translator.t('hex_dec_converter')
        self.setWindowTitle(title if title != 'hex_dec_converter' else "Hex/Dec Converter")
        self.setMinimumWidth(400)
        self._updating = False

        self.layout = QVBoxLayout(self)
        self.init_ui()

    @staticmethod
    def _default_translator():
        lang = QSettings('LabAutomation', 'App').value('language', 'en')
        return Translator(default_lang=str(lang))

    def init_ui(self):
        form = QFormLayout()
        self.hex_edit = QLineEdit()
        self.hex_edit.setPlaceholderText("0xFF")
        self.dec_edit = QLineEdit()
        self.dec_edit.setPlaceholderText("255")
        self.bin_edit = QLineEdit()
        self.bin_edit.setPlaceholderText("0b11111111")
        form.addRow(self.translator.t("hex_label"), self.hex_edit)
        form.addRow(self.translator.t("dec_label"), self.dec_edit)
        form.addRow(self.translator.t("bin_label"), self.bin_edit)
        self.layout.addLayout(form)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #c0392b;")
        self.layout.addWidget(self.status_label)

        self.hex_edit.textEdited.connect(lambda t: self._on_edited(t, 16, self.hex_edit))
        self.dec_edit.textEdited.connect(lambda t: self._on_edited(t, 10, self.dec_edit))
        self.bin_edit.textEdited.connect(lambda t: self._on_edited(t, 2, self.bin_edit))

    def convert_hex_to_dec(self, hex_value):
        """Converte una stringa esadecimale in stringa decimale."""
        return str(parse_int(hex_value, 16))

    def convert_dec_to_hex(self, dec_value):
        """Converte una stringa decimale in stringa esadecimale (con prefisso 0x)."""
        return format_hex(parse_int(dec_value, 10))

    def _on_edited(self, text, base, source):
        """Aggiorna gli altri campi quando l'utente modifica uno di essi."""
        if self._updating:
            return
        fields = {16: self.hex_edit, 10: self.dec_edit, 2: self.bin_edit}
        self._updating = True
        try:
            if not text.strip():
                self.status_label.setText("")
                for f in fields.values():
                    if f is not source:
                        f.clear()
                return
            try:
                value = parse_int(text, base)
            except ValueError:
                self.status_label.setText(self.translator.t("converter_invalid_value"))
                for f in fields.values():
                    if f is not source:
                        f.clear()
                return
            self.status_label.setText("")
            outputs = {16: format_hex(value), 10: str(value), 2: format_bin(value)}
            for b, f in fields.items():
                if f is not source:
                    f.setText(outputs[b])
        finally:
            self._updating = False
