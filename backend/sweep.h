// Copyright (C) 2025-2026 Erik Medeossi
// This file is part of Open Lab Automation.
// Licensed under the GNU General Public License v3.0; see the LICENSE file.

#ifndef SWEEP_H
#define SWEEP_H

#include "instrument.h"

#ifdef __cplusplus
extern "C" {
#endif

int sweep_run(const be_sweep_config_t *cfg,
              double *voltages_out,
              double *currents_out,
              be_progress_cb_t progress_cb);

#ifdef __cplusplus
}
#endif

#endif
