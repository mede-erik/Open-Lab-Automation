#!/usr/bin/env python3
import json

# Leggi la libreria strumenti
with open('Instruments_LIB/instruments_lib.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# Aggiungi il campo experimental a ogni modello
for section_key in ['power_supplies_series', 'dataloggers_series', 'oscilloscopes_series', 'electronic_loads_series']:
    if section_key in data['instrument_library']:
        for series in data['instrument_library'][section_key]:
            if 'models' in series:
                for model in series['models']:
                    if 'experimental' not in model:
                        model['experimental'] = False

# Salva il file aggiornato
with open('Instruments_LIB/instruments_lib.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
    f.write('\n')

print("✓ Campo 'experimental' aggiunto a tutti gli strumenti")
