// Copyright (C) 2025-2026 Erik Medeossi
// This file is part of Open Lab Automation.
// Licensed under the GNU General Public License v3.0; see the LICENSE file.

#ifndef BACKEND_H
#define BACKEND_H

#ifdef _WIN32
    #ifdef BACKEND_EXPORT
        #define BE_API __declspec(dllexport)
    #else
        #define BE_API __declspec(dllimport)
    #endif
#else
    #define BE_API
#endif

#ifdef __cplusplus
extern "C" {
#endif

#define BE_VERSION "0.1.0"

#define BE_OK               0
#define BE_ERR_GENERAL      -1
#define BE_ERR_CONNECT      -2
#define BE_ERR_SEND         -3
#define BE_ERR_RECV         -4
#define BE_ERR_TIMEOUT      -5
#define BE_ERR_PARSE        -6
#define BE_ERR_SWEEP        -7
#define BE_ERR_LIMIT        -8
#define BE_ERR_NOT_FOUND    -9
#define BE_ERR_INVALID_PARAM -10

#define BE_MAX_INSTRUMENTS  32
#define BE_MAX_SWEEP_POINTS 100000
#define BE_DEFAULT_PORT     5025

typedef int be_instr_t;

BE_API int be_init(void);
BE_API void be_cleanup(void);
BE_API const char *be_version(void);
BE_API const char *be_last_error(void);

BE_API int be_connect(be_instr_t *handle, const char *host, int port, int timeout_ms);
BE_API int be_disconnect(be_instr_t handle);
BE_API int be_send(be_instr_t handle, const char *command);
BE_API int be_receive(be_instr_t handle, char *buffer, int buf_size, int timeout_ms);
BE_API int be_receive_float(be_instr_t handle, double *value, int timeout_ms);
BE_API int be_receive_int(be_instr_t handle, int *value, int timeout_ms);

typedef struct {
    int n_instruments;
    be_instr_t *instruments;
    int *channels;
    int n_points;
    double *set_values;
    double settling_time_s;
} be_sweep_config_t;

typedef void (*be_progress_cb_t)(int current, int total);

BE_API int be_sweep_run(const be_sweep_config_t *cfg,
                         double *voltages_out,
                         double *currents_out,
                         be_progress_cb_t progress_cb);

#ifdef __cplusplus
}
#endif

#endif
