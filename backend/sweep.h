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
