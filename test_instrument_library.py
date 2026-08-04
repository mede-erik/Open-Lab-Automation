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
            'datalogger_modules'} <= keys


def test_get_all_types(lib):
    assert lib.get_all_types() == ['power_supply', 'datalogger', 'oscilloscope', 'electronic_load']


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


def test_trigger_slope_semantic_mapping():
    """RISE/FALL/EITHER del .was mappati sui valori accettati per serie."""
    from frontend.ui.RemoteControlTab import RemoteControlTab as R
    tektronix = ['RISe', 'FALL', 'EITher']
    rigol = ['POSitive', 'NEGative', 'RFALl']
    siglent = ['RISing', 'FALLing', 'ALTernate']
    assert R._map_trigger_slope_value('RISE', tektronix) == 'RISe'
    assert R._map_trigger_slope_value('FALL', tektronix) == 'FALL'
    assert R._map_trigger_slope_value('EITHER', tektronix) == 'EITher'
    assert R._map_trigger_slope_value('RISE', rigol) == 'POSitive'
    assert R._map_trigger_slope_value('FALL', rigol) == 'NEGative'
    assert R._map_trigger_slope_value('EITHER', rigol) == 'RFALl'
    assert R._map_trigger_slope_value('RISE', siglent) == 'RISing'
    assert R._map_trigger_slope_value('FALL', siglent) == 'FALLing'
    assert R._map_trigger_slope_value('EITHER', siglent) == 'ALTernate'
    assert R._map_trigger_slope_value('RISing', siglent) == 'RISing'
    assert R._map_trigger_slope_value('RISE', None) == 'RISE'


def test_trigger_slope_syntax_formatting(lib):
    """La syntax usa placeholder {slope}: la formattazione deve funzionare."""
    from frontend.ui.RemoteControlTab import RemoteControlTab as R
    series_ids = ('Tektronix_5_Series_MSO', 'Rigol_DS1000Z_Series',
                  'Siglent_SDS_HD_Series')
    for series_id in series_ids:
        series = next(s for s in lib.get_series('oscilloscope')
                      if s.get('series_id') == series_id)
        model_id = series['models'][0]['id']
        slope_cmd = lib.get_model_scpi('oscilloscope', series_id, model_id)
        slope = slope_cmd['set_trigger_slope']
        syntax = slope['set']['syntax']
        values = slope['parameters']['slope']['values']
        value = R._map_trigger_slope_value('RISE', values)
        assert '{slope}' in syntax
        cmd = syntax.format(slope=value)
        assert '{' not in cmd


def test_trigger_slope_fallback():
    """
    Senza set_trigger_slope in libreria (il submodule non va modificato),
    la sintassi viene derivata da set_trigger_source e il valore normalizzato.
    """
    from frontend.ui.RemoteControlTab import RemoteControlTab
    # Tek-style: TRIGger:A:EDGE:SOUrce CH{n}
    s = RemoteControlTab._get_trigger_slope_syntax_fallback(
        'TRIGger:A:EDGE:SOUrce CH{channel_number}')
    assert s == 'TRIGger:A:EDGE:SLOPe {value}'
    # Rigol/Siglent-style: :TRIGger:EDGE:SOURce C{n}
    s = RemoteControlTab._get_trigger_slope_syntax_fallback(
        ':TRIGger:EDGE:SOURce C{channel_number}')
    assert s == ':TRIGger:EDGE:SLOPe {value}'
    assert RemoteControlTab._get_trigger_slope_syntax_fallback(None) == \
        ':TRIGger:EDGE:SLOPe {value}'
    assert RemoteControlTab._get_trigger_slope_syntax_fallback(':NOPE x') is None
    # Normalizzazione valore (RISE non accettato da Siglent: -> RIS)
    assert RemoteControlTab._normalize_trigger_slope('RISE') == 'RIS'
    assert RemoteControlTab._normalize_trigger_slope('RISing') == 'RIS'
    assert RemoteControlTab._normalize_trigger_slope('FALL') == 'FALL'
    assert RemoteControlTab._normalize_trigger_slope('falling') == 'FALL'


def test_trigger_slope_mapping():
    """Il file .was usa RISE/FALL generici: mapping verso i valori accettati."""
    from frontend.ui.RemoteControlTab import RemoteControlTab
    assert RemoteControlTab._map_enum_value('RISE', ['RIS', 'FALL']) == 'RIS'
    assert RemoteControlTab._map_enum_value('RISE', ['RISe', 'FALL']) == 'RISe'
    assert RemoteControlTab._map_enum_value('FALL', ['RISE', 'FALL']) == 'FALL'
    assert RemoteControlTab._map_enum_value('FALL', ['RIS', 'FALLing']) == 'FALLing'
    assert RemoteControlTab._map_enum_value('RISE', None) == 'RISE'


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
