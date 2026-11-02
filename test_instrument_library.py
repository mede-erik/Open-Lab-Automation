# Tests per l'API della libreria strumenti (nuovo formato Instruments_LIB).

import json
import os

import pytest

ROOT = os.path.dirname(os.path.abspath(__file__))
LIB_PATH = os.path.join(ROOT, 'Instruments_LIB', 'instruments_lib.json')


@pytest.fixture(scope='module')
def lib():
    from frontend.core.LoadInstruments import LoadInstruments
    li = LoadInstruments()
    li.load_instruments(LIB_PATH)
    return li


def test_library_structure(lib):
    """La libreria deve avere le 4 chiavi serie + moduli datalogger."""
    keys = set(lib.instruments.keys())
    assert {'power_supplies_series', 'dataloggers_series',
            'oscilloscopes_series', 'electronic_loads_series',
            'datalogger_modules', 'switch_units_series'} <= keys


def test_get_all_types(lib):
    assert lib.get_all_types() == ['power_supply', 'datalogger', 'oscilloscope', 'electronic_load', 'switch_unit']


def test_get_series_key(lib):
    assert lib.get_series_key('power_supply') == 'power_supplies_series'
    assert lib.get_series_key('oscilloscope') == 'oscilloscopes_series'
    assert lib.get_series_key('boh') is None


def test_get_series(lib):
    assert len(lib.get_series('power_supply')) == 4
    assert len(lib.get_series('oscilloscope')) == 3
    assert lib.get_series('boh') is None


def test_get_models_and_scpi(lib):
    models = lib.get_models('oscilloscope', 'Siglent_SDS_HD_Series')
    assert models and any(m.get('id') == 'OSC_Siglent_SDS824X_HD' for m in models)
    scpi = lib.get_model_scpi('power_supply', 'OWON_ODP_Series', 'PSU_OWON_ODP3033')
    assert scpi and 'set_voltage' in scpi


def test_get_channel_ids(lib):
    ids = lib.get_channel_ids('oscilloscope', 'Siglent_SDS_HD_Series', 'OSC_Siglent_SDS824X_HD')
    assert ids == ['C1', 'C2', 'C3', 'C4']
    ids = lib.get_channel_ids('power_supply', 'OWON_ODP_Series', 'PSU_OWON_ODP3033')
    assert ids == ['1', '2', '3']


def test_get_channel_limits(lib):
    limits = lib.get_channel_limits('power_supply', 'OWON_ODP_Series', 'PSU_OWON_ODP3033', '1')
    assert limits['max_current'] == 3
    assert limits['max_voltage'] == 30
    default = lib.get_channel_limits(
        'power_supply', 'OWON_ODP_Series', 'PSU_OWON_ODP3033')
    assert default['max_current'] == 3
    assert default['max_voltage'] == 30
    limits = lib.get_channel_limits('electronic_load', 'Siglent_SDL1000X_E_Series', 'EL_Siglent_SDL1030X_E')
    assert limits['max_current'] == 30
    assert limits['max_voltage'] == 150
    assert limits['max_power'] == 300


def test_get_module_info(lib):
    module = lib.get_module_info('34901A')
    assert module is not None
    assert module.get('id') == '34901A'
    assert lib.get_module_info('NON_EXISTENT') is None


def test_get_module_channels(lib):
    assert lib.get_module_channels('34901A') == 20
    assert lib.get_module_channels('NON_EXISTENT') == 0


def test_get_enabled_compatible_modules(lib):
    mods = lib.get_enabled_compatible_modules('datalogger', 'Keysight_3497X_Series', 'DL_Keysight_34972A')
    ids = [m.get('id') for m in mods]
    assert '34901A' in ids and '34902A' in ids


def test_remote_control_get_scpi_cmd_strings():
    """get_scpi_cmd deve restituire stringhe (non dict) e formattabili."""
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from frontend.core.LoadInstruments import LoadInstruments
    from frontend.ui.RemoteControlTab import RemoteControlTab

    li = LoadInstruments()
    li.load_instruments(LIB_PATH)
    tab = RemoteControlTab.__new__(RemoteControlTab)
    tab.instruments_manager = li
    tab.logger = None

    inst = {'instrument_type': 'power_supply', 'series': 'OWON_ODP_Series',
            'model_id': 'PSU_OWON_ODP3033'}
    for action in ['set_voltage', 'set_current', 'read_voltage', 'read_current',
                   'output_on', 'output_off', 'output_state_query']:
        cmd = tab.get_scpi_cmd(inst, None, action)
        assert isinstance(cmd, str), f'{action}: {cmd!r}'
    cmd = tab.get_scpi_cmd(inst, None, 'set_voltage').replace('{value}', '5.0')
    assert cmd == 'VOLT 5.0'


def test_trigger_slope_in_library(lib):
    """set_trigger_slope ora presente nella libreria (submodule aggiornato)."""
    expected = {
        'Tektronix_5_Series_MSO': (
            'TRIGger:A:EDGE:SLOpe {slope}', ('RISe', 'FALL', 'EITher')),
        'Rigol_DS1000Z_Series': (
            ':TRIGger:EDGe:SLOPe {slope}', ('POSitive', 'NEGative', 'RFALl')),
        'Siglent_SDS_HD_Series': (
            ':TRIGger:EDGE:SLOPe {slope}', ('RISing', 'FALLing', 'ALTernate')),
    }
    for series_id, (syntax, values) in expected.items():
        series = next(s for s in lib.get_series('oscilloscope')
                      if s.get('series_id') == series_id)
        model_id = series['models'][0]['id']
        scpi = lib.get_model_scpi('oscilloscope', series_id, model_id)
        slope = scpi.get('set_trigger_slope')
        assert slope is not None, f'{series_id}: set_trigger_slope mancante'
        assert slope['set']['syntax'] == syntax
        assert tuple(slope['parameters']['slope']['values']) == values










def test_was_applier_parsing():
    """Helper del WAS applier: numeri canale e valori V/div."""
    from frontend.ui.RemoteControlTab import RemoteControlTab
    assert RemoteControlTab._extract_channel_number('CH1') == 1
    assert RemoteControlTab._extract_channel_number('C4') == 4
    assert RemoteControlTab._extract_channel_number('3') == 3
    assert RemoteControlTab._extract_channel_number(None) is None
    assert RemoteControlTab._parse_voltage_value('2V') == 2.0
    assert RemoteControlTab._parse_voltage_value('100mV') == 0.1
    assert RemoteControlTab._parse_voltage_value('0.5') == 0.5
    assert RemoteControlTab._parse_voltage_value('zzz') is None


def test_resolve_model_commands_override_remove_patch():
    """Model scpi_commands: full definition replaces, null removes, patch deep-merges."""
    from frontend.core.LoadInstruments import LoadInstruments
    series = {
        'common_scpi_commands': {
            'set_a': {'set': {'syntax': 'A {value}'}, 'parameters': {'value': {'type': 'float'}}},
            'set_b': {'set': {'syntax': 'B {mode}'},
                      'parameters': {'mode': {'type': 'string', 'values': ['X', 'Y']}}},
            'set_c': {'set': {'syntax': 'C'}},
            'set_d': {'set': {'syntax': 'D'}},
        }
    }
    model = {'id': 'M', 'scpi_commands': {
        'set_a': {'set': {'syntax': 'A2 {value}'}, 'parameters': {'value': {'type': 'float'}}},
        'set_b': {'patch': {'parameters': {'mode': {'values': ['X', 'Y', 'Z']}}}},
        'set_c': None,
        'set_x': {'patch': {'set': {'syntax': 'ignored'}}},
    }}
    out = LoadInstruments.resolve_model_commands(series, model)
    assert out['set_a']['set']['syntax'] == 'A2 {value}'
    assert out['set_b']['set']['syntax'] == 'B {mode}'
    assert out['set_b']['parameters']['mode'] == {'type': 'string', 'values': ['X', 'Y', 'Z']}
    assert 'set_c' not in out
    assert out['set_d'] == {'set': {'syntax': 'D'}}
    assert 'set_x' not in out
    # the series must not be modified
    assert series['common_scpi_commands']['set_b']['parameters']['mode']['values'] == ['X', 'Y']
