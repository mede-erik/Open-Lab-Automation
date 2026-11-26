# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

import logging
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QCheckBox, QComboBox, QLabel, QPushButton
from PyQt6.QtCore import Qt, QSettings

logger = logging.getLogger('frontend.ui.SettingsDialog')

# The languages are shown by their own name, whatever the language of the application
LANGUAGE_NAMES = {'it': 'Italiano', 'en': 'English', 'fr': 'Français', 'es': 'Español', 'de': 'Deutsch'}

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
        
        logger.debug("Creating helper function t()...")
        def t(key, default=None):
            if self.translator and hasattr(self.translator, 't'):
                return self.translator.t(key)
            return default or key
        
        logger.debug("Setting up settings dialog")
        self.setWindowTitle(t('settings', 'Settings'))
        self.setModal(True)
        
        layout = QVBoxLayout()
        
        theme_layout = QHBoxLayout()
        self.theme_label = QLabel(t('theme', 'Theme') + ':')
        self.theme_combo = QComboBox()
        self.theme_combo.addItem(t('theme_system', 'System'), 'system')
        self.theme_combo.addItem(t('theme_dark', 'Dark'), 'dark')
        self.theme_combo.addItem(t('theme_light', 'Light'), 'light')
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
            # each language by its own name ("Italiano"), the code is the data of the item
            for code in sorted(self.translator.available_langs):
                self.lang_combo.addItem(LANGUAGE_NAMES.get(code, code), code)
            if hasattr(self.translator, 'current_lang'):
                self._select_language(self.translator.current_lang)
        self.lang_combo.currentIndexChanged.connect(
            lambda _index: self.change_language(self.lang_combo.currentData()))
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

        # Experimental instruments setting
        self.experimental_checkbox = QCheckBox(t('enable_experimental_instruments', 'Enable experimental instruments in the instrument list'))
        layout.addWidget(self.experimental_checkbox)
        # A measurement that fails is not kept (it would fill the history of a cable or a device)
        self.keep_failed_checkbox = QCheckBox(t('keep_failed_runs', 'Keep the measurements that failed'))
        self.keep_failed_checkbox.setToolTip(t('keep_failed_runs_help', 'A measurement that fails is deleted when it ends.'))
        layout.addWidget(self.keep_failed_checkbox)
        # Apply button
        btn_layout = QHBoxLayout()
        self.apply_btn = QPushButton(t('apply', 'Apply'))
        self.apply_btn.clicked.connect(self.apply_settings)
        btn_layout.addWidget(self.apply_btn)
        layout.addLayout(btn_layout)
        self.setLayout(layout)
        self.load_settings()
        self._set_naming_enabled(self.adv_naming_checkbox.isChecked())

    def _select_language(self, code):
        """Select the language ``code`` in the combo box (nothing if it is not there)."""
        index = self.lang_combo.findData(code)
        if index >= 0:
            self.lang_combo.setCurrentIndex(index)

    def toggle_advanced_naming(self, state):
        """
        Enable or disable advanced naming toggles.
        :param state: Qt.CheckState.Checked or Qt.CheckState.Unchecked
        """
        self._set_naming_enabled(state == Qt.CheckState.Checked)
        self.save_settings()

    def _set_naming_enabled(self, enabled):
        """Enable or disable the advanced naming toggles (nothing is saved: used while loading)."""
        self.inst_toggle.setEnabled(enabled)
        self.eff_toggle.setEnabled(enabled)
        self.was_toggle.setEnabled(enabled)

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
        settings.setValue('show_experimental_instruments', self.experimental_checkbox.isChecked())
        settings.setValue('keep_failed_runs', self.keep_failed_checkbox.isChecked())

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
        # Showing the saved language must not run ``change_language``: that saves the settings
        # (the boxes below are not loaded yet, so it wrote their defaults over what was saved) and
        # closes the window.
        self.lang_combo.blockSignals(True)
        self._select_language(lang)
        self.lang_combo.blockSignals(False)
        
        # Set theme combo based on loaded theme
        for i in range(self.theme_combo.count()):
            if self.theme_combo.itemData(i) == theme:
                self.theme_combo.setCurrentIndex(i)
                break
        
        # Loading must not save: the settings are written only when the person changes one (a
        # save here wrote the defaults of the boxes not loaded yet over what was saved)
        self.adv_naming_checkbox.blockSignals(True)
        self.adv_naming_checkbox.setChecked(adv_naming)
        self.adv_naming_checkbox.blockSignals(False)
        self.inst_toggle.setChecked(adv_inst)
        self.eff_toggle.setChecked(adv_eff)
        self.was_toggle.setChecked(adv_was)

        # Load experimental instruments setting
        show_exp = settings.value('show_experimental_instruments', False, type=bool)
        self.experimental_checkbox.setChecked(show_exp)
        self.keep_failed_checkbox.setChecked(settings.value('keep_failed_runs', False, type=bool))
        self._set_naming_enabled(adv_naming)

    def apply_settings(self):
        """
        Apply and save settings, update main window, and close the dialog.
        """
        self.save_settings()
        
        # Apply theme
        theme = self.theme_combo.currentData()
        logger.debug(f"Applying theme: {theme}")
        parent = self.parent()
        if parent is not None and hasattr(parent, 'apply_theme'):
            parent.apply_theme(theme)
        
        # Update translations if language changed
        if parent is not None and hasattr(parent, 'update_translations'):
            parent.update_translations()
        self.close()
