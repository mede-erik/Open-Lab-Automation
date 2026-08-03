#include "sweep.h"
#include <math.h>

static const char *_scpi_sel_channel = "INST:NSEL %d";
static const char *_scpi_set_voltage = "VOLT %.6f";
static const char *_scpi_meas_voltage = "MEAS:VOLT?";
static const char *_scpi_meas_current = "MEAS:CURR?";

static int _do_set_point(instrument_t *inst, int channel, double value) {
    char cmd[256];

    snprintf(cmd, sizeof(cmd), _scpi_sel_channel, channel);
    int ret = instrument_send(inst, cmd);
    if (ret != BE_OK) return ret;

    snprintf(cmd, sizeof(cmd), _scpi_set_voltage, value);
    ret = instrument_send(inst, cmd);
    if (ret != BE_OK) return ret;

    return BE_OK;
}

static int _do_measure(instrument_t *inst, double *voltage, double *current) {
    int ret = instrument_send(inst, _scpi_meas_voltage);
    if (ret != BE_OK) return ret;

    ret = instrument_receive_float(inst, voltage, 5000);
    if (ret != BE_OK) return ret;

    ret = instrument_send(inst, _scpi_meas_current);
    if (ret != BE_OK) return ret;

    ret = instrument_receive_float(inst, current, 5000);
    if (ret != BE_OK) return ret;

    return BE_OK;
}

int sweep_run(const be_sweep_config_t *cfg,
              double *voltages_out,
              double *currents_out,
              be_progress_cb_t progress_cb) {
    if (!cfg || !voltages_out || !currents_out)
        return BE_ERR_INVALID_PARAM;
    if (cfg->n_instruments < 1 || cfg->n_points < 1)
        return BE_ERR_INVALID_PARAM;
    if (cfg->n_points > BE_MAX_SWEEP_POINTS)
        return BE_ERR_LIMIT;

    instrument_t *inst = instrument_pool_get(cfg->instruments[0]);
    if (!inst)
        return BE_ERR_NOT_FOUND;

    int channel = (cfg->channels && cfg->n_instruments > 0) ? cfg->channels[0] : 1;
    int settling_ms = (int)(cfg->settling_time_s * 1000.0);

    for (int i = 0; i < cfg->n_points; i++) {
        int ret = _do_set_point(inst, channel, cfg->set_values[i]);
        if (ret != BE_OK) return ret;

        if (settling_ms > 0)
            BE_SLEEP_MS(settling_ms);

        ret = _do_measure(inst, &voltages_out[i], &currents_out[i]);
        if (ret != BE_OK) return ret;

        if (progress_cb)
            progress_cb(i + 1, cfg->n_points);
    }

    return BE_OK;
}
