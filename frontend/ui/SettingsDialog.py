import os
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QCheckBox, QComboBox, QLabel, QPushButton
from PyQt6.QtCore import Qt, QSettings

# =========================
# SettingsDialog
# =========================
class SettingsDialog(QDialog):
    """
    Dialog for application settings (theme, language, advanced naming).
    """
    def __init__(self, parent=None, translator=None):
        """
        Initialize the settings dialog with theme, language, and naming options.
        :param parent: Parent widget.
        :param translator: Translator instance.
        """
        super().__init__(parent)
        
        self.translator = translator
        
        print("[SettingsDialog DEBUG] Creating helper function t()...")
        # Helper function for safe translations
        def t(key, default=None):
            if self.translator and hasattr(self.translator, 't'):
                return self.translator.t(key)
            return default or key
        print("[SettingsDialog DEBUG] Helper t() creato")
        
        print("[SettingsDialog DEBUG] Impostazione titolo finestra...")
        self.setWindowTitle(t('settings', 'Settings'))
        print(f"[SettingsDialog DEBUG] Titolo impostato: {self.windowTitle()}")
        
        print("[SettingsDialog DEBUG] Impostazione modale...")
        self.setModal(True)
        print("[SettingsDialog DEBUG] Dialog impostato come modale")
        
        print("[SettingsDialog DEBUG] Creazione layout principale...")
        layout = QVBoxLayout()
        print("[SettingsDialog DEBUG] Layout creato")
        
        print("[SettingsDialog DEBUG] Creazione theme selector...")
        # Theme selector
        theme_layout = QHBoxLayout()
        self.theme_label = QLabel(t('theme', 'Theme')+':')
        self.theme_combo = QComboBox()
        self.theme_combo.addItem(t('theme_system', 'System'), 'system')
        self.theme_combo.addItem(t('theme_dark', 'Dark'), 'dark')
        self.theme_combo.addItem(t('theme_light', 'Light'), 'light')
        print(f"[SettingsDialog DEBUG] Theme combo creato con {self.theme_combo.count()} opzioni")
        # Non collegare il segnale qui - il tema verrà applicato solo quando si clicca Applica
        theme_layout.addWidget(self.theme_label)
        theme_layout.addWidget(self.theme_combo)
        layout.addLayout(theme_layout)
        # Language dropdown
        lang_layout = QHBoxLayout()
        self.lang_label = QLabel(t('language', 'Language')+':')
        self.lang_combo = QComboBox()
        # Load available languages from the translator
        self.lang_combo.clear()
        if self.translator and hasattr(self.translator, 'available_langs'):
            self.lang_combo.addItems(self.translator.available_langs)
            if hasattr(self.translator, 'current_lang'):
                self.lang_combo.setCurrentText(self.translator.current_lang)
        self.lang_combo.currentTextChanged.connect(self.change_language)
        lang_layout.addWidget(self.lang_label)
        lang_layout.addWidget(self.lang_combo)
        layout.addLayout(lang_layout)
        # Advanced naming settings
        self.naming_group = QVBoxLayout()
        self.adv_naming_checkbox = QCheckBox(t('enable_advanced_naming', 'Enable Advanced Naming'))
        self.adv_naming_checkbox.stateChanged.connect(self.toggle_advanced_naming)
        self.naming_group.addWidget(self.adv_naming_checkbox)
        # File type toggles
        self.inst_toggle = QCheckBox(t('advanced_naming_inst', 'Advanced naming for .inst files'))
        self.eff_toggle = QCheckBox(t('advanced_naming_eff', 'Advanced naming for .eff files'))
        self.was_toggle = QCheckBox(t('advanced_naming_was', 'Advanced naming for .was files'))
        self.naming_group.addWidget(self.inst_toggle)
        self.naming_group.addWidget(self.eff_toggle)
        self.naming_group.addWidget(self.was_toggle)
        layout.addLayout(self.naming_group)
        # Apply button
        btn_layout = QHBoxLayout()
        self.apply_btn = QPushButton(t('apply', 'Apply'))
        self.apply_btn.clicked.connect(self.apply_settings)
        btn_layout.addWidget(self.apply_btn)
        layout.addLayout(btn_layout)
        self.setLayout(layout)
        self.load_settings()
        self.toggle_advanced_naming(self.adv_naming_checkbox.isChecked())

    def toggle_advanced_naming(self, state):
        """
        Enable or disable advanced naming toggles.
        :param state: Qt.CheckState.Checked or Qt.CheckState.Unchecked
        """
        enabled = state == Qt.CheckState.Checked
        self.inst_toggle.setEnabled(enabled)
        self.eff_toggle.setEnabled(enabled)
        self.was_toggle.setEnabled(enabled)
        self.save_settings()

    def change_language(self, lang):
        """
        Change the application language and update translations.
        :param lang: Language code.
        """
        if self.translator and hasattr(self.translator, 'set_language'):
            self.translator.set_language(lang)
            if hasattr(self.translator, 't'):
                self.lang_label.setText(self.translator.t('language')+':')
        
            parent = self.parent()
            if parent is not None and hasattr(parent, 'update_translations'):
                parent.update_translations()
        
        self.save_settings()
        self.close()

    def save_settings(self):
        """
        Save current settings to QSettings.
        """
        settings = QSettings('LabAutomation', 'App')
        current_lang = 'en'  # default
        if self.translator and hasattr(self.translator, 'current_lang'):
            current_lang = self.translator.current_lang
        
        settings.setValue('language', current_lang)
        settings.setValue('theme', self.theme_combo.currentData())
        settings.setValue('advanced_naming', self.adv_naming_checkbox.isChecked())
        settings.setValue('advanced_naming_inst', self.inst_toggle.isChecked())
        settings.setValue('advanced_naming_eff', self.eff_toggle.isChecked())
        settings.setValue('advanced_naming_was', self.was_toggle.isChecked())

    def load_settings(self):
        """
        Load settings from QSettings and update UI accordingly.
        """
        settings = QSettings('LabAutomation', 'App')
        current_lang = 'en'  # default
        if self.translator and hasattr(self.translator, 'current_lang'):
            current_lang = self.translator.current_lang
        
        lang = settings.value('language', current_lang)
        theme = settings.value('theme', 'dark', type=str)  # Default: dark
        adv_naming = settings.value('advanced_naming', False, type=bool)
        adv_inst = settings.value('advanced_naming_inst', False, type=bool)
        adv_eff = settings.value('advanced_naming_eff', False, type=bool)
        adv_was = settings.value('advanced_naming_was', False, type=bool)
        self.lang_combo.setCurrentText(lang)
        
        # Set theme combo based on loaded theme
        for i in range(self.theme_combo.count()):
            if self.theme_combo.itemData(i) == theme:
                self.theme_combo.setCurrentIndex(i)
                break
        
        self.adv_naming_checkbox.setChecked(adv_naming)
        self.inst_toggle.setChecked(adv_inst)
        self.eff_toggle.setChecked(adv_eff)
        self.was_toggle.setChecked(adv_was)
        self.toggle_advanced_naming(Qt.CheckState.Checked if adv_naming else Qt.CheckState.Unchecked)

    def apply_settings(self):
        """
        Apply and save settings, update main window, and close the dialog.
        """
        self.save_settings()
        
        # Apply theme
        theme = self.theme_combo.currentData()
        print(f"[SettingsDialog DEBUG] Applicazione tema: {theme}")
        parent = self.parent()
        if parent is not None and hasattr(parent, 'apply_theme'):
            parent.apply_theme(theme)
        
        # Update translations if language changed
        if parent is not None and hasattr(parent, 'update_translations'):
            parent.update_translations()
        self.close()
