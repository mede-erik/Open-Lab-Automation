// Copyright (C) 2025-2026 Erik Medeossi
// This file is part of Open Lab Automation.
// Licensed under the GNU General Public License v3.0; see the LICENSE file.

#include <stdarg.h>
#include "backend.h"
#include "instrument.h"
#include "sweep.h"

static char _last_error[512] = {0};
static bool _initialized = false;

static void _set_error(const char *fmt, ...) {
    va_list args;
    va_start(args, fmt);
    vsnprintf(_last_error, sizeof(_last_error) - 1, fmt, args);
    va_end(args);
}

int be_init(void) {
    if (_initialized)
        return BE_OK;

#ifdef _WIN32
    WSADATA wsa;
    int ret = WSAStartup(MAKEWORD(2, 2), &wsa);
    if (ret != 0) {
        _set_error("WSAStartup failed: %d", ret);
        return BE_ERR_GENERAL;
    }
#endif

    instrument_pool_init();
    _initialized = true;
    return BE_OK;
}

void be_cleanup(void) {
    instrument_pool_cleanup();

#ifdef _WIN32
    WSACleanup();
#endif

    _initialized = false;
}

const char *be_version(void) {
    return BE_VERSION;
}

const char *be_last_error(void) {
    return _last_error;
}

int be_connect(be_instr_t *handle, const char *host, int port, int timeout_ms) {
    int ret = instrument_pool_connect(handle, host, port, timeout_ms);
    if (ret != BE_OK) {
        _set_error("Failed to connect to %s:%d (error %d)", host ? host : "(null)", port, ret);
    }
    return ret;
}

int be_disconnect(be_instr_t handle) {
    return instrument_pool_disconnect(handle);
}

int be_send(be_instr_t handle, const char *command) {
    instrument_t *inst = instrument_pool_get(handle);
    if (!inst) {
        _set_error("Invalid instrument handle: %d", handle);
        return BE_ERR_NOT_FOUND;
    }
    int ret = instrument_send(inst, command);
    if (ret != BE_OK)
        _set_error("Send failed on handle %d (error %d)", handle, ret);
    return ret;
}

int be_receive(be_instr_t handle, char *buffer, int buf_size, int timeout_ms) {
    instrument_t *inst = instrument_pool_get(handle);
    if (!inst) {
        _set_error("Invalid instrument handle: %d", handle);
        return BE_ERR_NOT_FOUND;
    }
    int ret = instrument_receive(inst, buffer, buf_size, timeout_ms);
    if (ret < 0)
        _set_error("Receive failed on handle %d (error %d)", handle, ret);
    return ret;
}

int be_receive_float(be_instr_t handle, double *value, int timeout_ms) {
    instrument_t *inst = instrument_pool_get(handle);
    if (!inst) {
        _set_error("Invalid instrument handle: %d", handle);
        return BE_ERR_NOT_FOUND;
    }
    int ret = instrument_receive_float(inst, value, timeout_ms);
    if (ret != BE_OK)
        _set_error("Float receive failed on handle %d (error %d)", handle, ret);
    return ret;
}

int be_receive_int(be_instr_t handle, int *value, int timeout_ms) {
    instrument_t *inst = instrument_pool_get(handle);
    if (!inst) {
        _set_error("Invalid instrument handle: %d", handle);
        return BE_ERR_NOT_FOUND;
    }
    int ret = instrument_receive_int(inst, value, timeout_ms);
    if (ret != BE_OK)
        _set_error("Int receive failed on handle %d (error %d)", handle, ret);
    return ret;
}

int be_sweep_run(const be_sweep_config_t *cfg,
                  double *voltages_out,
                  double *currents_out,
                  be_progress_cb_t progress_cb) {
    int ret = sweep_run(cfg, voltages_out, currents_out, progress_cb);
    if (ret != BE_OK) {
        _set_error("Sweep failed with error: %d", ret);
    }
    return ret;
}
