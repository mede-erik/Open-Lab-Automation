# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""
Datalogger Slot Configuration Dialog

This dialog provides a comprehensive interface for configuring slot-based dataloggers.
It allows users to:
- Select modules for each slot from compatible and enabled modules in the library
- Configure channels for each module based on its capabilities
- Validate module compatibility and availability
- Handle errors with standardized error codes

Error codes used:
- [DL-001]: Datalogger has no slots configured
- [DL-002]: Invalid module selected
- [DL-003]: Module not compatible with this datalogger
- [DL-004]: Module not found in library
- [DL-006]: Module is disabled in library
- [DL-007]: Invalid slot number
- [DL-008]: Configuration error
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, 
    QGroupBox, QTableWidget, QCheckBox, QLineEdit, 
    QScrollArea, QWidget, QDialogButtonBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QDoubleValidator
from frontend.core.LoadInstruments import LoadInstruments
from frontend.core.Translator import Translator
from frontend.ui.layout_utils import fit_table_to_rows, resize_to_screen
from frontend.core.errorhandler import ErrorCode, DataloggerError, get_error_handler
from frontend.ui.channel_settings import SettingsCells, model_options
from frontend.core.errorhandler import show_problem


class DataloggerSlotConfigDialog(QDialog):
    """
    Dialog for configuring slot-based dataloggers with module selection and channel configuration.
    """
    
    def __init__(self, instrument, load_instruments: LoadInstruments, translator: Translator, parent=None):
        """
        Initialize the datalogger slot configuration dialog.
        
        Args:
            instrument (dict): Instrument data dictionary
            load_instruments (LoadInstruments): Instance for accessing instrument library
            translator (Translator): Instance for translations
            parent (QWidget): Parent widget
        """
        super().__init__(parent)
        self.instrument = instrument
        self.load_instruments = load_instruments
        self.translator = translator
        self.error_handler = get_error_handler()
        
        self.setWindowTitle(self.translator.t('datalogger_slot_config'))
        resize_to_screen(self, 1000, 700)
        
        # Get datalogger capabilities
        type_name = instrument.get('instrument_type', 'datalogger')
        series_id = instrument.get('series', '')
        model_id = instrument.get('model_id', '')
        
        try:
            capabilities = self.load_instruments.get_model_capabilities(type_name, series_id, model_id)
            if not capabilities:
                raise DataloggerError(
                    ErrorCode.DL_CONFIGURATION_ERROR,
                    "Could not load datalogger capabilities"
                )
            
            self.num_slots = capabilities.get('number_of_slots', 0)
            if self.num_slots <= 0:
                raise DataloggerError(
                    ErrorCode.DL_NO_SLOTS,
                    f"Datalogger {model_id} has no slots configured"
                )
            
            # Get compatible and enabled modules
            self.compatible_modules = self.load_instruments.get_enabled_compatible_modules(
                type_name, series_id, model_id
            )
            
            if not self.compatible_modules:
                show_problem(
                    self,
                    self.translator.t('warning'),
                    self.translator.t('no_compatible_modules_warning'),
                    code="DL-003",
                )
        
        except DataloggerError as e:
            self.error_handler.handle_error(e, self.translator.t("err_dl_init_failed"), code="DL-008")
            self.num_slots = 0
            self.compatible_modules = []
        except Exception as e:
            self.error_handler.handle_error(e, self.translator.t("err_dl_init_failed"), code="DL-008")
            self.num_slots = 0
            self.compatible_modules = []
        
        # Initialize or load slots configuration
        self.slots = instrument.get('slots', [])
        self._initialize_slots()
        
        self.init_ui()
    
    def _initialize_slots(self):
        """Initialize slots structure if not present or incomplete."""
        # Ensure we have the correct number of slots
        while len(self.slots) < self.num_slots:
            self.slots.append({
                'slot_number': len(self.slots) + 1,
                'module_id': None,
                'channels': []
            })
        
        # Truncate if we have too many slots
        self.slots = self.slots[:self.num_slots]
        
        # Update slot numbers
        for idx, slot in enumerate(self.slots):
            slot['slot_number'] = idx + 1
    
    def init_ui(self):
        """Initialize the user interface."""
        main_layout = QVBoxLayout(self)
        
        # Header with info
        header_label = QLabel(self.translator.t('datalogger_slot_config_info'))
        header_label.setWordWrap(True)
        header_label.setProperty("class", "infobox")
        main_layout.addWidget(header_label)
        
        # Scroll area for slots
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        slots_widget = QWidget()
        self.slots_layout = QVBoxLayout(slots_widget)
        
        # Create UI for each slot
        self.slot_widgets = []
        for slot_idx in range(self.num_slots):
            slot_widget = self._create_slot_widget(slot_idx)
            self.slots_layout.addWidget(slot_widget)
            self.slot_widgets.append(slot_widget)
        
        scroll.setWidget(slots_widget)
        main_layout.addWidget(scroll)
        
        # Buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        main_layout.addWidget(button_box)
    
    def _create_slot_widget(self, slot_idx):
        """
        Create a widget for a single slot configuration.
        
        Args:
            slot_idx (int): Index of the slot (0-based)
        
        Returns:
            QGroupBox: Widget containing slot configuration UI
        """
        slot = self.slots[slot_idx]
        slot_number = slot.get('slot_number', slot_idx + 1)
        
        group = QGroupBox(f"{self.translator.t('slot')} {slot_number}")
        group.setProperty('slot_idx', slot_idx)
        layout = QVBoxLayout(group)
        
        # Module selection
        module_layout = QHBoxLayout()
        module_label = QLabel(self.translator.t('select_module'))
        module_layout.addWidget(module_label)
        
        module_combo = QComboBox()
        module_combo.setProperty('slot_idx', slot_idx)
        
        # Add empty option
        module_combo.addItem(self.translator.t('empty_slot'), None)
        
        # Add compatible modules
        for module in self.compatible_modules:
            module_id = module.get('id', module.get('module_id'))
            module_name = module.get('name', module_id)
            num_channels = module.get('capabilities', {}).get('number_of_channels', 0)
            module_combo.addItem(
                f"{module_id} - {module_name} ({num_channels} {self.translator.t('channels')})",
                module_id
            )
        
        # Set current selection
        current_module_id = slot.get('module_id')
        if current_module_id:
            idx = module_combo.findData(current_module_id)
            if idx >= 0:
                module_combo.setCurrentIndex(idx)
        
        module_combo.currentIndexChanged.connect(
            lambda idx, s=slot_idx: self._on_module_changed(s, idx)
        )
        
        module_layout.addWidget(module_combo, 1)
        layout.addLayout(module_layout)
        
        # Module info label
        info_label = QLabel()
        info_label.setProperty('slot_idx', slot_idx)
        info_label.setWordWrap(True)
        info_label.setProperty("class", "muted")
        layout.addWidget(info_label)
        self._update_module_info(slot_idx, info_label, current_module_id)
        
        # Channel configuration table (initially hidden if no module)
        channel_table = QTableWidget()
        channel_table.setProperty('slot_idx', slot_idx)
        channel_table.setVisible(current_module_id is not None)
        layout.addWidget(channel_table)
        
        if current_module_id:
            self._populate_channel_table(slot_idx, channel_table, current_module_id)
        
        return group
    
    def _update_module_info(self, slot_idx, info_label, module_id):
        """
        Update the information label for a module.
        
        Args:
            slot_idx (int): Slot index
            info_label (QLabel): Label widget to update
            module_id (str): Module ID to display info for
        """
        if not module_id:
            info_label.setText(self.translator.t('slot_empty_info'))
            info_label.setVisible(True)
            return
        
        try:
            module_info = self.load_instruments.get_module_info(module_id)
            if not module_info:
                raise DataloggerError(
                    ErrorCode.DL_MODULE_NOT_FOUND,
                    f"Module {module_id} not found in library"
                )
            
            info_parts = []
            capabilities = module_info.get('capabilities', {})
            info_parts.append(f"📊 {self.translator.t('channels')}: {capabilities.get('number_of_channels', 0)}")
            
            if 'max_voltage' in capabilities:
                info_parts.append(f"⚡ Max: {capabilities['max_voltage']}V")
            
            if 'speed' in capabilities:
                info_parts.append(f"⚙️ {self.translator.t('speed')}: {capabilities['speed']} ch/s")
            
            meas_types = capabilities.get('measurement_types', [])
            if meas_types:
                info_parts.append(f"📈 {self.translator.t('types')}: {', '.join(meas_types)}")
            
            info_label.setText(" | ".join(info_parts))
            info_label.setVisible(True)
        
        except DataloggerError as e:
            self.error_handler.handle_error(
                e, f"Error loading module {module_id} information", show_dialog=False, code="DL-004")
            info_label.setText(f"⚠️ {self.translator.t('module_not_found')}: {module_id}")
            info_label.setVisible(True)
    
    def _on_module_changed(self, slot_idx, combo_idx):
        """
        Handle module selection change for a slot.
        
        Args:
            slot_idx (int): Index of the slot
            combo_idx (int): Index of the combo box selection
        """
        # Find the combo box and get selected module_id
        slot_widget = self.slot_widgets[slot_idx]
        module_combo = slot_widget.findChild(QComboBox)
        module_id = module_combo.currentData()
        
        # Update slot data
        self.slots[slot_idx]['module_id'] = module_id
        
        # Find info label and update it
        info_label = slot_widget.findChild(QLabel, "", Qt.FindChildOption.FindDirectChildrenOnly)
        if info_label and info_label.property('slot_idx') == slot_idx:
            self._update_module_info(slot_idx, info_label, module_id)
        
        # Find channel table and update it
        channel_table = slot_widget.findChild(QTableWidget)
        if channel_table:
            if module_id:
                self._populate_channel_table(slot_idx, channel_table, module_id)
                channel_table.setVisible(True)
            else:
                channel_table.setVisible(False)
                channel_table.setRowCount(0)
                self.slots[slot_idx]['channels'] = []
    
    def _model_options(self):
        """What the model of the datalogger lets you choose for a channel (see channel_settings)."""
        if getattr(self, '_options', None) is None:
            self._options = model_options(self.instrument)
        return self._options

    def _populate_channel_table(self, slot_idx, table, module_id):
        """
        Populate the channel configuration table for a module.
        
        Args:
            slot_idx (int): Index of the slot
            table (QTableWidget): Table widget to populate
            module_id (str): Module ID
        """
        try:
            module_info = self.load_instruments.get_module_info(module_id)
            if not module_info:
                raise DataloggerError(
                    ErrorCode.DL_MODULE_NOT_FOUND,
                    f"Module {module_id} not found in library"
                )
            
            num_channels = module_info.get('capabilities', {}).get('number_of_channels', 0)
            capabilities = module_info.get('capabilities', {})
            meas_types = capabilities.get('measurement_types', ['VOLT:DC'])
            
            # Get or initialize channels
            slot = self.slots[slot_idx]
            channels = slot.get('channels', [])
            
            # Ensure we have the correct number of channels
            while len(channels) < num_channels:
                channels.append({
                    'enabled': False,
                    'name': f"CH{len(channels)+1}",
                    'meas_type': meas_types[0] if meas_types else 'VOLT:DC',
                    'attenuation': 1.0,
                    'unit': 'V'
                })
            
            channels = channels[:num_channels]
            slot['channels'] = channels
            
            # Configure table
            table.setRowCount(num_channels)
            table.setColumnCount(9)
            table.setHorizontalHeaderLabels([
                self.translator.t('enable'),
                self.translator.t('channel_name'),
                self.translator.t('measurement_type'),
                self.translator.t('attenuation'),
                self.translator.t('unit'),
                self.translator.t('channel_range'),
                self.translator.t('channel_nplc'),
                self.translator.t('channel_zero'),
                self.translator.t('channel_impedance'),
            ])
            options = self._model_options()
            self._cells = {k: v for k, v in getattr(self, '_cells', {}).items() if k[0] != slot_idx}
            
            # Populate rows
            for row, ch in enumerate(channels):
                # Enable checkbox
                chk = QCheckBox()
                chk.setChecked(ch.get('enabled', False))
                chk.stateChanged.connect(
                    lambda state, s=slot_idx, r=row: self._on_channel_enabled_changed(s, r, state)
                )
                table.setCellWidget(row, 0, chk)
                
                # Channel name
                name_edit = QLineEdit(ch.get('name', f'CH{row+1}'))
                name_edit.textChanged.connect(
                    lambda val, s=slot_idx, r=row: self._on_channel_name_changed(s, r, val)
                )
                table.setCellWidget(row, 1, name_edit)
                
                # Measurement type
                type_combo = QComboBox()
                type_combo.addItems(meas_types)
                type_combo.setCurrentText(ch.get('meas_type', meas_types[0] if meas_types else ''))
                type_combo.currentTextChanged.connect(
                    lambda val, s=slot_idx, r=row: self._on_channel_meas_type_changed(s, r, val)
                )
                table.setCellWidget(row, 2, type_combo)
                
                # Attenuation
                att_edit = QLineEdit(str(ch.get('attenuation', 1.0)))
                att_edit.setValidator(QDoubleValidator(0.0000000001, 1e6, 10))
                att_edit.setPlaceholderText("1.0")
                att_edit.textChanged.connect(
                    lambda val, s=slot_idx, r=row: self._on_channel_attenuation_changed(s, r, val)
                )
                table.setCellWidget(row, 3, att_edit)
                
                # Unit
                unit_edit = QLineEdit(ch.get('unit', 'V'))
                unit_edit.textChanged.connect(
                    lambda val, s=slot_idx, r=row: self._on_channel_unit_changed(s, r, val)
                )
                table.setCellWidget(row, 4, unit_edit)

                # Range, integration time, zero and input impedance (what the model has)
                cells = SettingsCells(ch, options, self.translator.t)
                self._cells[(slot_idx, row)] = cells
                for offset, widget in enumerate(cells.widgets):
                    table.setCellWidget(row, 5 + offset, widget)
            
            # Columns and height: the name and the attenuation share the room, the others are as wide
            # as their header; the table fills its cells and has no scroll bar of its own
            fit_table_to_rows(table, fixed_columns=(0, 2, 4, 5, 6, 7, 8), min_column_width=80)
        
        except DataloggerError as e:
            self.error_handler.handle_error(
                e, self.translator.t("err_dl_channels_failed").format(module=module_id), code="DL-002")
            table.setRowCount(0)
        except Exception as e:
            self.error_handler.handle_error(
                e, self.translator.t("err_dl_channels_failed").format(module=module_id), code="DL-002")
            table.setRowCount(0)
    
    def _on_channel_enabled_changed(self, slot_idx, row, state):
        """Handle channel enabled state change."""
        try:
            self.slots[slot_idx]['channels'][row]['enabled'] = bool(state)
        except (IndexError, KeyError) as e:
            self.error_handler.handle_error(e, f"Error updating channel enable state for slot {slot_idx+1}, channel {row+1}", show_dialog=False, code="DL-008")
    
    def _on_channel_name_changed(self, slot_idx, row, val):
        """Handle channel name change."""
        try:
            self.slots[slot_idx]['channels'][row]['name'] = val
        except (IndexError, KeyError) as e:
            self.error_handler.handle_error(e, f"Error updating channel name for slot {slot_idx+1}, channel {row+1}", show_dialog=False, code="DL-008")
    
    def _on_channel_meas_type_changed(self, slot_idx, row, val):
        """Handle measurement type change."""
        try:
            self.slots[slot_idx]['channels'][row]['meas_type'] = val
            cells = getattr(self, '_cells', {}).get((slot_idx, row))
            if cells is not None:  # the settings depend on the function: they start again
                cells.fill_function(val)
        except (IndexError, KeyError) as e:
            self.error_handler.handle_error(e, f"Error updating measurement type for slot {slot_idx+1}, channel {row+1}", show_dialog=False, code="DL-008")
    
    def _on_channel_attenuation_changed(self, slot_idx, row, val):
        """Handle attenuation value change."""
        try:
            val_clean = str(val).replace(',', '.')
            self.slots[slot_idx]['channels'][row]['attenuation'] = float(val_clean) if val_clean else 1.0
        except (ValueError, IndexError, KeyError) as e:
            self.error_handler.handle_error(e, f"Error updating attenuation for slot {slot_idx+1}, channel {row+1}", show_dialog=False, code="DL-008")
            try:
                self.slots[slot_idx]['channels'][row]['attenuation'] = 1.0
            except (IndexError, KeyError):
                pass
    
    def _on_channel_unit_changed(self, slot_idx, row, val):
        """Handle unit change."""
        try:
            self.slots[slot_idx]['channels'][row]['unit'] = val
        except (IndexError, KeyError) as e:
            self.error_handler.handle_error(e, f"Error updating unit for slot {slot_idx+1}, channel {row+1}", show_dialog=False, code="DL-008")
    
    def accept(self):
        """Validate and save configuration before closing."""
        try:
            # Validate that at least one slot has a module
            has_module = any(slot.get('module_id') for slot in self.slots)
            if not has_module:
                show_problem(
                    self,
                    self.translator.t('warning'),
                    self.translator.t('no_modules_configured_warning'),
                    code="DL-001",
                )
                return
            
            # Save slots to instrument
            self.instrument['slots'] = self.slots
            
            # Generate flat channel list for compatibility with existing code
            all_channels = []
            for slot in self.slots:
                if slot.get('module_id'):
                    for index, ch in enumerate(slot.get('channels', [])):
                        if ch.get('enabled', False):
                            # Add slot information to channel
                            ch_copy = ch.copy()
                            ch_copy['slot_number'] = slot.get('slot_number')
                            # channel number of the instrument: slot * 100 + channel (e.g. "103")
                            ch_copy['channel_id'] = str(
                                int(slot.get('slot_number') or 0) * 100 + index + 1)
                            ch_copy['module_id'] = slot.get('module_id')
                            all_channels.append(ch_copy)
            
            self.instrument['channels'] = all_channels
            
            super().accept()
        
        except Exception as e:
            self.error_handler.handle_error(e, self.translator.t("err_dl_save_failed"), code="DL-008")
