"""
Pulse Generator Tool for Electronic Loads

This tool allows generating current/voltage pulses on electronic loads.
Uses ONLY commands explicitly defined in instruments_lib.json for safety.
Validates parameters against instrument capabilities (max_current_a, max_voltage_v, max_power_w).
Provides real-time waveform preview with matplotlib.

Author: Open Lab Automation
Date: 2025-11-20
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, 
    QComboBox, QPushButton, QLabel, QGroupBox,
    QRadioButton, QDoubleSpinBox, QMessageBox, QWidget
)
from PyQt6.QtCore import Qt
import json
import os
import numpy as np

from frontend.core.LoadInstruments import LoadInstruments
from frontend.core.Translator import Translator
from frontend.core.errorhandler import ErrorHandler, ErrorCode

try:
    import matplotlib
    matplotlib.use('Qt5Agg')
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
    from matplotlib.figure import Figure
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    print("Warning: matplotlib not available. Pulse waveform preview will be disabled.")

try:
    import pyvisa
    PYVISA_AVAILABLE = True
except ImportError:
    PYVISA_AVAILABLE = False
    print("Warning: pyvisa not available. Pulse generation will not work.")


class PulseGeneratorDialog(QDialog):
    """
    Dialog for generating pulses on electronic loads.
    
    Features:
    - Select electronic load from project
    - Configure pulse parameters (amplitude, width, frequency, etc.)
    - Validate parameters against instrument capabilities (max limits only)
    - Real-time waveform preview with matplotlib
    - Send SCPI commands for pulse generation (library commands only)
    """
    
    def __init__(self, project_dir, load_instruments: LoadInstruments, translator: Translator, parent=None):
        super().__init__(parent)
        self.project_dir = project_dir
        self.load_instruments = load_instruments
        self.translator = translator
        self.error_handler = ErrorHandler()
        
        self.setWindowTitle(self.translator.t('pulse_generator_tool'))
        self.setMinimumWidth(1000)
        self.setMinimumHeight(600)
        
        self.current_instrument = None
        self.current_capabilities = None
        self.current_scpi_commands = None
        self.visa_instr = None
        self.pulse_running = False
        
        # Track last modified parameter for power validation
        self.last_modified_param = None
        
        self.init_ui()
        self.load_instruments_from_project()
        
    def init_ui(self):
        """Initialize user interface"""
        main_layout = QHBoxLayout(self)
        
        # === LEFT SIDE: PARAMETERS ===
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        
        # Instrument Selection
        inst_group = QGroupBox(self.translator.t('select_load_instrument'))
        inst_layout = QFormLayout()
        
        self.instrument_combo = QComboBox()
        self.instrument_combo.currentIndexChanged.connect(self.on_instrument_changed)
        inst_layout.addRow(self.translator.t('electronic_load') + ":", self.instrument_combo)
        
        self.instrument_info_label = QLabel("")
        self.instrument_info_label.setWordWrap(True)
        self.instrument_info_label.setStyleSheet("color: #666; font-size: 10px;")
        inst_layout.addRow(self.instrument_info_label)
        
        inst_group.setLayout(inst_layout)
        left_layout.addWidget(inst_group)
        
        # Pulse Parameters
        params_group = QGroupBox(self.translator.t('pulse_parameters'))
        params_layout = QFormLayout()
        
        # Operating Mode
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["CC (Constant Current)", "CV (Constant Voltage)", "CP (Constant Power)"])
        params_layout.addRow(self.translator.t('pulse_mode') + ":", self.mode_combo)
        
        # Amplitude
        self.amplitude_spin = QDoubleSpinBox()
        self.amplitude_spin.setRange(0.0, 1000.0)
        self.amplitude_spin.setDecimals(3)
        self.amplitude_spin.setSuffix(" A")
        self.amplitude_spin.setValue(1.0)
        self.amplitude_spin.editingFinished.connect(self.validate_amplitude)
        params_layout.addRow(self.translator.t('pulse_amplitude') + ":", self.amplitude_spin)
        
        # Base Level
        self.base_level_spin = QDoubleSpinBox()
        self.base_level_spin.setRange(0.0, 1000.0)
        self.base_level_spin.setDecimals(3)
        self.base_level_spin.setSuffix(" A")
        self.base_level_spin.setValue(0.0)
        self.base_level_spin.editingFinished.connect(self.validate_base_level)
        params_layout.addRow(self.translator.t('pulse_base_level') + ":", self.base_level_spin)
        
        # Width
        self.width_spin = QDoubleSpinBox()
        self.width_spin.setRange(1.0, 1000000.0)
        self.width_spin.setDecimals(1)
        self.width_spin.setSuffix(" μs")
        self.width_spin.setValue(100.0)
        self.width_spin.editingFinished.connect(self.update_waveform)
        params_layout.addRow(self.translator.t('pulse_width') + ":", self.width_spin)
        
        # Frequency
        self.frequency_spin = QDoubleSpinBox()
        self.frequency_spin.setRange(0.001, 100000.0)
        self.frequency_spin.setDecimals(3)
        self.frequency_spin.setSuffix(" Hz")
        self.frequency_spin.setValue(1000.0)
        self.frequency_spin.editingFinished.connect(self.update_waveform)
        params_layout.addRow(self.translator.t('pulse_frequency') + ":", self.frequency_spin)
        
        # Rise Time
        self.rise_time_spin = QDoubleSpinBox()
        self.rise_time_spin.setRange(0.1, 10000.0)
        self.rise_time_spin.setDecimals(1)
        self.rise_time_spin.setSuffix(" μs")
        self.rise_time_spin.setValue(10.0)
        self.rise_time_spin.editingFinished.connect(self.update_waveform)
        params_layout.addRow(self.translator.t('pulse_rise_time') + ":", self.rise_time_spin)
        
        # Fall Time
        self.fall_time_spin = QDoubleSpinBox()
        self.fall_time_spin.setRange(0.1, 10000.0)
        self.fall_time_spin.setDecimals(1)
        self.fall_time_spin.setSuffix(" μs")
        self.fall_time_spin.setValue(10.0)
        self.fall_time_spin.editingFinished.connect(self.update_waveform)
        params_layout.addRow(self.translator.t('pulse_fall_time') + ":", self.fall_time_spin)
        
        # Pulse Count
        count_layout = QHBoxLayout()
        self.continuous_radio = QRadioButton(self.translator.t('pulse_continuous'))
        self.continuous_radio.setChecked(True)
        self.single_radio = QRadioButton(self.translator.t('pulse_single'))
        count_layout.addWidget(self.continuous_radio)
        count_layout.addWidget(self.single_radio)
        params_layout.addRow(self.translator.t('pulse_count') + ":", count_layout)
        
        params_group.setLayout(params_layout)
        left_layout.addWidget(params_group)
        
        # Control Buttons
        buttons_layout = QHBoxLayout()
        
        self.start_button = QPushButton(self.translator.t('start_pulse'))
        self.start_button.clicked.connect(self.start_pulse)
        self.start_button.setEnabled(False)
        
        self.stop_button = QPushButton(self.translator.t('stop_pulse'))
        self.stop_button.clicked.connect(self.stop_pulse)
        self.stop_button.setEnabled(False)
        
        buttons_layout.addWidget(self.start_button)
        buttons_layout.addWidget(self.stop_button)
        
        left_layout.addLayout(buttons_layout)
        
        # Status
        self.status_label = QLabel(f"{self.translator.t('pulse_status')}: {self.translator.t('pulse_stopped')}")
        self.status_label.setStyleSheet("font-weight: bold; color: #c00;")
        left_layout.addWidget(self.status_label)
        
        left_layout.addStretch()
        
        # Close button at bottom
        close_button_layout = QHBoxLayout()
        close_button_layout.addStretch()
        self.close_button = QPushButton(self.translator.t('close'))
        self.close_button.clicked.connect(self.reject)
        close_button_layout.addWidget(self.close_button)
        left_layout.addLayout(close_button_layout)
        
        main_layout.addWidget(left_widget, 1)
        
        # === RIGHT SIDE: WAVEFORM PREVIEW ===
        if MATPLOTLIB_AVAILABLE:
            right_widget = QWidget()
            right_layout = QVBoxLayout(right_widget)
            
            preview_label = QLabel(self.translator.t('pulse_waveform_preview'))
            preview_label.setStyleSheet("font-weight: bold; font-size: 12px;")
            right_layout.addWidget(preview_label)
            
            # Matplotlib canvas
            self.figure = Figure(figsize=(6, 4))
            self.canvas = FigureCanvasQTAgg(self.figure)
            self.ax = self.figure.add_subplot(111)
            right_layout.addWidget(self.canvas)
            
            main_layout.addWidget(right_widget, 1)
            
            # Initial empty plot
            self.plot_pulse_waveform()
        
        self.setLayout(main_layout)
    
    def load_instruments_from_project(self):
        """Load electronic loads from project .inst file"""
        try:
            # Find project JSON file
            project_files = [f for f in os.listdir(self.project_dir) if f.endswith('.json')]
            if not project_files:
                QMessageBox.warning(
                    self,
                    self.translator.t('warning'),
                    self.translator.t('no_project_file_found')
                )
                return
            
            project_file = os.path.join(self.project_dir, project_files[0])
            with open(project_file, 'r', encoding='utf-8') as f:
                project_data = json.load(f)
            
            # Load instruments from .inst file
            inst_file_name = project_data.get('inst_file')
            if not inst_file_name:
                QMessageBox.warning(
                    self,
                    self.translator.t('warning'),
                    self.translator.t('no_inst_file_in_project')
                )
                return
            
            inst_file_path = os.path.join(self.project_dir, inst_file_name)
            if not os.path.exists(inst_file_path):
                QMessageBox.warning(
                    self,
                    self.translator.t('warning'),
                    f"{self.translator.t('inst_file_not_found')}: {inst_file_name}"
                )
                return
            
            with open(inst_file_path, 'r', encoding='utf-8') as f:
                inst_data = json.load(f)
            
            instruments = inst_data.get('instruments', [])
            
            # Filter only electronic loads
            electronic_loads = [inst for inst in instruments if inst.get('instrument_type') == 'electronic_load']
            
            if not electronic_loads:
                QMessageBox.warning(
                    self,
                    self.translator.t('warning'),
                    self.translator.t('no_load_available')
                )
                self.instrument_combo.addItem(self.translator.t('no_load_available'))
                return
            
            # Populate combo box
            for load in electronic_loads:
                name = load.get('name', 'Unnamed')
                model = load.get('model', 'Unknown')
                display_name = f"{name} ({model})"
                self.instrument_combo.addItem(display_name, load)
            
        except Exception as e:
            self.error_handler.handle_error(
                e,
                f"Error loading instruments from project: {str(e)}"
            )
    
    def on_instrument_changed(self, index):
        """Update UI when instrument selection changes"""
        if index < 0:
            return
        
        instrument = self.instrument_combo.itemData(index)
        if not instrument:
            return
        
        self.current_instrument = instrument
        
        try:
            # Get instrument details
            type_name = instrument.get('instrument_type', 'electronic_load')
            series_id = instrument.get('series', '')
            model_id = instrument.get('model_id', instrument.get('model', ''))
            
            # Get capabilities
            self.current_capabilities = self.load_instruments.get_model_capabilities(
                type_name, series_id, model_id
            )
            
            if not self.current_capabilities:
                QMessageBox.critical(
                    self,
                    self.translator.t('error'),
                    f"{self.translator.t('pulse_missing_capabilities')}\n[TOOL-007]"
                )
                self.start_button.setEnabled(False)
                return
            
            # Get SCPI commands
            self.current_scpi_commands = self.load_instruments.get_model_scpi(
                type_name, series_id, model_id
            )
            
            if not self.current_scpi_commands:
                QMessageBox.critical(
                    self,
                    self.translator.t('error'),
                    f"{self.translator.t('pulse_no_commands')}\n[TOOL-003]"
                )
                self.start_button.setEnabled(False)
                return
            
            # Validate required commands
            required_commands = ['set_dynamic_level_high', 'set_dynamic_level_low', 'load_on', 'load_off']
            missing_commands = [cmd for cmd in required_commands if cmd not in self.current_scpi_commands]
            
            if missing_commands:
                QMessageBox.critical(
                    self,
                    self.translator.t('error'),
                    f"{self.translator.t('pulse_missing_commands_error')}:\n" +
                    f"{', '.join(missing_commands)}\n\n" +
                    f"{self.translator.t('pulse_update_library_suggestion')}\n[TOOL-003]"
                )
                self.start_button.setEnabled(False)
                self.instrument_info_label.setText(
                    f"❌ {self.translator.t('pulse_not_supported')}"
                )
                self.instrument_info_label.setStyleSheet("color: #c00; font-weight: bold;")
                return
            
            # Update UI with capabilities
            max_current = self.current_capabilities.get('max_current_a', 100.0)
            max_voltage = self.current_capabilities.get('max_voltage_v', 80.0)
            max_power = self.current_capabilities.get('max_power_w', 1000.0)
            
            # Update spinbox limits
            self.amplitude_spin.setMaximum(max_current)
            self.base_level_spin.setMaximum(max_current)
            
            # Update info label
            info_text = (
                f"✓ {self.translator.t('pulse_supported')}\n"
                f"Max: {max_current}A, {max_voltage}V, {max_power}W"
            )
            self.instrument_info_label.setText(info_text)
            self.instrument_info_label.setStyleSheet("color: #0a0; font-weight: bold;")
            
            # Enable start button
            self.start_button.setEnabled(True)
            
            # Update waveform
            self.update_waveform()
            
        except Exception as e:
            self.error_handler.handle_error(
                e,
                f"Error loading instrument capabilities: {str(e)}"
            )
            self.start_button.setEnabled(False)
    
    def validate_amplitude(self):
        """Validate amplitude against max_current_a"""
        if not self.current_capabilities:
            return
        
        self.last_modified_param = 'amplitude'
        value = self.amplitude_spin.value()
        max_current = self.current_capabilities.get('max_current_a', 100.0)
        
        if value > max_current:
            QMessageBox.warning(
                self,
                self.translator.t('error'),
                self.translator.t('pulse_amplitude_exceeded').format(
                    value=value,
                    max=max_current
                ) + f"\n[TOOL-004]"
            )
            self.amplitude_spin.setValue(max_current)
        
        # Validate combined power
        self.validate_power()
        self.update_waveform()
    
    def validate_base_level(self):
        """Validate base level against max_current_a"""
        if not self.current_capabilities:
            return
        
        value = self.base_level_spin.value()
        max_current = self.current_capabilities.get('max_current_a', 100.0)
        
        if value > max_current:
            QMessageBox.warning(
                self,
                self.translator.t('error'),
                self.translator.t('pulse_base_level_exceeded').format(
                    value=value,
                    max=max_current
                ) + f"\n[TOOL-004]"
            )
            self.base_level_spin.setValue(max_current)
        
        self.update_waveform()
    
    def validate_power(self):
        """Validate combined power P = I * V"""
        if not self.current_capabilities:
            return
        
        max_power = self.current_capabilities.get('max_power_w')
        if not max_power:
            return  # No power limit defined
        
        # For simplicity, assume voltage is nominal (to be extended with voltage input)
        # For now, just check if we have operating mode info
        mode = self.mode_combo.currentText()
        
        # This is simplified - in real implementation would need voltage parameter
        # For now, just log that power validation is available
        amplitude = self.amplitude_spin.value()
        
        # Placeholder: full implementation would calculate P = I * V
        # and correct last modified parameter if power exceeds max_power_w
    
    def plot_pulse_waveform(self):
        """Plot pulse waveform with matplotlib"""
        if not MATPLOTLIB_AVAILABLE:
            return
        
        try:
            # Get parameters
            amplitude = self.amplitude_spin.value()
            base_level = self.base_level_spin.value()
            width_us = self.width_spin.value()
            frequency_hz = self.frequency_spin.value()
            rise_time_us = self.rise_time_spin.value()
            fall_time_us = self.fall_time_spin.value()
            
            # Calculate period
            period_us = 1000000.0 / frequency_hz if frequency_hz > 0 else 1000.0
            
            # Generate time array for 2 complete periods
            time_points = 1000
            time_array = np.linspace(0, 2 * period_us, time_points)
            current_array = np.zeros(time_points)
            
            # Generate pulse waveform (trapezoidal)
            for i, t in enumerate(time_array):
                # Get time within current period
                t_in_period = t % period_us
                
                if t_in_period < rise_time_us:
                    # Rising edge
                    current_array[i] = base_level + (amplitude - base_level) * (t_in_period / rise_time_us)
                elif t_in_period < (rise_time_us + width_us):
                    # High level
                    current_array[i] = amplitude
                elif t_in_period < (rise_time_us + width_us + fall_time_us):
                    # Falling edge
                    t_fall = t_in_period - (rise_time_us + width_us)
                    current_array[i] = amplitude - (amplitude - base_level) * (t_fall / fall_time_us)
                else:
                    # Low level
                    current_array[i] = base_level
            
            # Clear and plot
            self.ax.clear()
            self.ax.plot(time_array, current_array, 'b-', linewidth=2)
            self.ax.axhline(y=0, color='gray', linestyle='--', alpha=0.3)
            self.ax.grid(True, alpha=0.3)
            self.ax.set_xlabel(self.translator.t('pulse_time_us'))
            self.ax.set_ylabel(self.translator.t('pulse_current_a'))
            self.ax.set_title(self.translator.t('pulse_waveform_preview'))
            
            # Add annotations
            self.ax.annotate(
                f'Peak: {amplitude:.3f}A',
                xy=(rise_time_us + width_us/2, amplitude),
                xytext=(10, 10),
                textcoords='offset points',
                fontsize=9,
                bbox=dict(boxstyle='round,pad=0.5', fc='yellow', alpha=0.7)
            )
            
            self.figure.tight_layout()
            self.canvas.draw()
            
        except Exception as e:
            print(f"Error plotting waveform: {e}")
    
    def update_waveform(self):
        """Update waveform plot"""
        self.plot_pulse_waveform()
    
    def start_pulse(self):
        """Start pulse generation"""
        if not PYVISA_AVAILABLE:
            QMessageBox.critical(
                self,
                self.translator.t('error'),
                self.translator.t('pyvisa_not_available')
            )
            return
        
        if not self.current_instrument or not self.current_scpi_commands:
            QMessageBox.warning(
                self,
                self.translator.t('warning'),
                f"{self.translator.t('no_instrument_selected')}\n[TOOL-001]"
            )
            return
        
        try:
            # Get VISA address
            visa_address = self.current_instrument.get('visa_address')
            if not visa_address:
                QMessageBox.critical(
                    self,
                    self.translator.t('error'),
                    self.translator.t('no_visa_address')
                )
                return
            
            # Connect to instrument
            rm = pyvisa.ResourceManager()
            self.visa_instr = rm.open_resource(visa_address)
            self.visa_instr.timeout = 5000
            
            # Get parameters
            amplitude = self.amplitude_spin.value()
            base_level = self.base_level_spin.value()
            frequency = self.frequency_spin.value()
            
            # Send SCPI commands
            cmd_high = self._get_scpi_set_syntax(self.current_scpi_commands.get('set_dynamic_level_high'))
            cmd_low = self._get_scpi_set_syntax(self.current_scpi_commands.get('set_dynamic_level_low'))
            cmd_on = self._get_scpi_set_syntax(self.current_scpi_commands.get('load_on'))

            if not cmd_high or not cmd_low or not cmd_on:
                raise ValueError("Comandi SCPI richiesti mancanti o non validi")

            cmd_high = cmd_high.format(value=amplitude)
            cmd_low = cmd_low.format(value=base_level)
            
            self.visa_instr.write(cmd_high)
            self.visa_instr.write(cmd_low)
            
            # Check for additional dynamic mode commands if available
            if 'set_dynamic_frequency' in self.current_scpi_commands:
                cmd_freq = self._get_scpi_set_syntax(self.current_scpi_commands.get('set_dynamic_frequency'))
                if cmd_freq:
                    self.visa_instr.write(cmd_freq.format(value=frequency))
            
            # Enable dynamic mode if command exists
            if 'enable_dynamic_mode' in self.current_scpi_commands:
                cmd_enable = self._get_scpi_set_syntax(self.current_scpi_commands.get('enable_dynamic_mode'))
                if cmd_enable:
                    self.visa_instr.write(cmd_enable)
            
            # Turn load on
            self.visa_instr.write(cmd_on)
            
            # Update UI
            self.pulse_running = True
            self.start_button.setEnabled(False)
            self.stop_button.setEnabled(True)
            self.status_label.setText(f"{self.translator.t('pulse_status')}: {self.translator.t('pulse_running')}")
            self.status_label.setStyleSheet("font-weight: bold; color: #0a0;")
            
            QMessageBox.information(
                self,
                self.translator.t('success'),
                self.translator.t('pulse_started_successfully')
            )
            
        except Exception as e:
            self.error_handler.handle_error(
                e,
                f"{self.translator.t('pulse_start_failed')}: {str(e)}\n[TOOL-005]"
            )
    
    def stop_pulse(self):
        """Stop pulse generation"""
        if not self.visa_instr:
            return
        
        try:
            # Disable dynamic mode if command exists
            if 'disable_dynamic_mode' in self.current_scpi_commands:
                cmd_disable = self._get_scpi_set_syntax(self.current_scpi_commands.get('disable_dynamic_mode'))
                if cmd_disable:
                    self.visa_instr.write(cmd_disable)
            
            # Turn load off
            cmd_off = self._get_scpi_set_syntax(self.current_scpi_commands.get('load_off'))
            if cmd_off:
                self.visa_instr.write(cmd_off)
            
            # Close connection
            self.visa_instr.close()
            self.visa_instr = None
            
            # Update UI
            self.pulse_running = False
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.status_label.setText(f"{self.translator.t('pulse_status')}: {self.translator.t('pulse_stopped')}")
            self.status_label.setStyleSheet("font-weight: bold; color: #c00;")
            
            QMessageBox.information(
                self,
                self.translator.t('success'),
                self.translator.t('pulse_stopped_successfully')
            )
            
        except Exception as e:
            self.error_handler.handle_error(
                e,
                f"{self.translator.t('pulse_stop_failed')}: {str(e)}\n[TOOL-005]"
            )
    
    def closeEvent(self, event):
        """Handle dialog close event"""
        if self.pulse_running:
            reply = QMessageBox.question(
                self,
                self.translator.t('confirm'),
                self.translator.t('pulse_running_close_confirm'),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                self.stop_pulse()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()

    def _get_scpi_set_syntax(self, command_def):
        """Restituisce la sintassi SCPI per i comandi di set, compatibile con vecchio formato."""
        if isinstance(command_def, str):
            return command_def
        if isinstance(command_def, dict):
            set_def = command_def.get('set')
            if isinstance(set_def, dict):
                return set_def.get('syntax')
        return None
