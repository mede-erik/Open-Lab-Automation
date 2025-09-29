import os
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QCheckBox, QComboBox, QLabel, QPushButton
from PyQt5.QtCore import Qt, QSettings

# =========================
# SettingsDialog
# =========================
class SettingsDialog(QDialog):
    """
    Dialog for application settings (theme, language, advanced naming).
    Singleton pattern is used to ensure only one instance exists.
    """
    _instance = None
    def __new__(cls, *args, **kwargs):
        """
        Create a new instance of the dialog or return the existing one.
        Ensures that only one settings dialog is open at a time.
        """
        if cls._instance is None:
            cls._instance = super(SettingsDialog, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    def __init__(self, parent=None, translator=None):
        """
        Initialize the settings dialog with theme, language, and naming options.
        :param parent: Parent widget.
        :param translator: Translator instance.
        """
        if self._initialized:
            return
        super().__init__(parent)
        self.translator = translator
        self.setWindowTitle(self.translator.t('settings'))
        self.setModal(True)
        layout = QVBoxLayout()
        # Dark theme toggle
        dark_layout = QHBoxLayout()
        self.dark_theme_switch = QCheckBox(self.translator.t('enable_dark_theme'))
        self.dark_theme_switch.stateChanged.connect(self.toggle_dark_theme)
        dark_layout.addWidget(self.dark_theme_switch)
        layout.addLayout(dark_layout)
        # Language dropdown
        lang_layout = QHBoxLayout()
        self.lang_label = QLabel(self.translator.t('language')+':')
        self.lang_combo = QComboBox()
        # Reload languages from the correct path
        lang_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), self.translator.lang_dir)
        self.translator.lang_dir = lang_dir
        self.translator.load_languages()
        self.lang_combo.clear()
        self.lang_combo.addItems(self.translator.available_langs)
        self.lang_combo.setCurrentText(self.translator.current_lang)
        self.lang_combo.currentTextChanged.connect(self.change_language)
        lang_layout.addWidget(self.lang_label)
        lang_layout.addWidget(self.lang_combo)
        layout.addLayout(lang_layout)
        # Advanced naming settings
        self.naming_group = QVBoxLayout()
        self.adv_naming_checkbox = QCheckBox(self.translator.t('enable_advanced_naming'))
        self.adv_naming_checkbox.stateChanged.connect(self.toggle_advanced_naming)
        self.naming_group.addWidget(self.adv_naming_checkbox)
        # File type toggles
        self.inst_toggle = QCheckBox(self.translator.t('advanced_naming_inst'))
        self.eff_toggle = QCheckBox(self.translator.t('advanced_naming_eff'))
        self.was_toggle = QCheckBox(self.translator.t('advanced_naming_was'))
        self.naming_group.addWidget(self.inst_toggle)
        self.naming_group.addWidget(self.eff_toggle)
        self.naming_group.addWidget(self.was_toggle)
        layout.addLayout(self.naming_group)
        # Apply button
        btn_layout = QHBoxLayout()
        self.apply_btn = QPushButton(self.translator.t('apply'))
        self.apply_btn.clicked.connect(self.apply_settings)
        btn_layout.addWidget(self.apply_btn)
        layout.addLayout(btn_layout)
        self.setLayout(layout)
        self._initialized = True
        self.load_settings()
        self.toggle_advanced_naming(self.adv_naming_checkbox.isChecked())

    def toggle_dark_theme(self, state):
        """
        Enable or disable dark theme.
        :param state: Qt.Checked or Qt.Unchecked
        """
        if state == Qt.Checked:
            self.parent().set_dark_theme()
        else:
            self.parent().setStyleSheet("")
        self.save_settings()

    def toggle_advanced_naming(self, state):
        """
        Enable or disable advanced naming toggles.
        :param state: Qt.Checked or Qt.Unchecked
        """
        enabled = state == Qt.Checked
        self.inst_toggle.setEnabled(enabled)
        self.eff_toggle.setEnabled(enabled)
        self.was_toggle.setEnabled(enabled)
        self.save_settings()

    def change_language(self, lang):
        """
        Change the application language and update translations.
        :param lang: Language code.
        """
        self.translator.set_language(lang)
        self.lang_label.setText(self.translator.t('language')+':')
        self.parent().update_translations()
        self.save_settings()
        self.close()

    def save_settings(self):
        """
        Save current settings to QSettings.
        """
        settings = QSettings('LabAutomation', 'App')
        settings.setValue('language', self.translator.current_lang)
        settings.setValue('dark_theme', self.dark_theme_switch.isChecked())
        settings.setValue('advanced_naming', self.adv_naming_checkbox.isChecked())
        settings.setValue('advanced_naming_inst', self.inst_toggle.isChecked())
        settings.setValue('advanced_naming_eff', self.eff_toggle.isChecked())
        settings.setValue('advanced_naming_was', self.was_toggle.isChecked())

    def load_settings(self):
        """
        Load settings from QSettings and update UI accordingly.
        """
        settings = QSettings('LabAutomation', 'App')
        lang = settings.value('language', self.translator.current_lang)
        dark = settings.value('dark_theme', False, type=bool)
        adv_naming = settings.value('advanced_naming', False, type=bool)
        adv_inst = settings.value('advanced_naming_inst', False, type=bool)
        adv_eff = settings.value('advanced_naming_eff', False, type=bool)
        adv_was = settings.value('advanced_naming_was', False, type=bool)
        self.lang_combo.setCurrentText(lang)
        self.dark_theme_switch.setChecked(dark)
        self.adv_naming_checkbox.setChecked(adv_naming)
        self.inst_toggle.setChecked(adv_inst)
        self.eff_toggle.setChecked(adv_eff)
        self.was_toggle.setChecked(adv_was)
        self.toggle_advanced_naming(adv_naming)

    def apply_settings(self):
        """
        Apply and save settings, update main window, and close the dialog.
        """
        self.save_settings()
        self.parent().load_settings()
        self.parent().update_translations()
        self.close()
