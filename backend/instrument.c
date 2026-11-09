// Copyright (C) 2025-2026 Erik Medeossi
// This file is part of Open Lab Automation.
// Licensed under the GNU General Public License v3.0; see the LICENSE file.

#include "instrument.h"

static instrument_t _pool[BE_MAX_INSTRUMENTS];
static int _pool_count = 0;

int instrument_pool_init(void) {
    _pool_count = 0;
    memset(_pool, 0, sizeof(_pool));
    return BE_OK;
}

void instrument_pool_cleanup(void) {
    for (int i = 0; i < BE_MAX_INSTRUMENTS; i++) {
        if (_pool[i].connected) {
            be_tcp_close(_pool[i].socket);
            _pool[i].connected = false;
        }
    }
    _pool_count = 0;
}

int instrument_pool_connect(be_instr_t *handle, const char *host, int port, int timeout_ms) {
    if (!handle || !host)
        return BE_ERR_INVALID_PARAM;

    /* Reuse a slot freed by a previous disconnect, otherwise take a new one */
    int idx = -1;
    for (int i = 0; i < _pool_count; i++) {
        if (!_pool[i].connected) {
            idx = i;
            break;
        }
    }
    if (idx < 0) {
        if (_pool_count >= BE_MAX_INSTRUMENTS)
            return BE_ERR_LIMIT;
        idx = _pool_count;
    }

    be_socket_t sock = be_tcp_connect(host, port, timeout_ms);
    if (sock == BE_INVALID_SOCKET)
        return BE_ERR_CONNECT;

    if (idx == _pool_count)
        _pool_count++;
    _pool[idx].socket = sock;
    _pool[idx].port = port;
    _pool[idx].connected = true;
    strncpy(_pool[idx].host, host, sizeof(_pool[idx].host) - 1);
    _pool[idx].host[sizeof(_pool[idx].host) - 1] = '\0';

    *handle = idx;
    return BE_OK;
}

int instrument_pool_disconnect(be_instr_t handle) {
    if (handle < 0 || handle >= _pool_count)
        return BE_ERR_NOT_FOUND;
    if (!_pool[handle].connected)
        return BE_OK;

    be_tcp_close(_pool[handle].socket);
    _pool[handle].connected = false;
    return BE_OK;
}

instrument_t *instrument_pool_get(be_instr_t handle) {
    if (handle < 0 || handle >= _pool_count)
        return NULL;
    if (!_pool[handle].connected)
        return NULL;
    return &_pool[handle];
}

int instrument_send(instrument_t *inst, const char *command) {
    if (!inst || !inst->connected)
        return BE_ERR_INVALID_PARAM;

    if (!command)
        return BE_ERR_INVALID_PARAM;

    int cmd_len = (int)strlen(command);

    int ret = be_tcp_send(inst->socket, command, cmd_len);
    if (ret < 0)
        return ret;

    ret = be_tcp_send(inst->socket, "\n", 1);
    if (ret < 0)
        return ret;

    return BE_OK;
}

int instrument_receive(instrument_t *inst, char *buffer, int buf_size, int timeout_ms) {
    if (!inst || !inst->connected || !buffer)
        return BE_ERR_INVALID_PARAM;
    return be_tcp_recv(inst->socket, buffer, buf_size, timeout_ms);
}

int instrument_receive_float(instrument_t *inst, double *value, int timeout_ms) {
    if (!value)
        return BE_ERR_INVALID_PARAM;
    char buf[256];
    int n = instrument_receive(inst, buf, sizeof(buf), timeout_ms);
    if (n < 0)
        return n;

    char *end = NULL;
    double parsed = strtod(buf, &end);
    if (end == buf || (*end != '\0' && *end != '\n' && *end != '\r'))
        return BE_ERR_PARSE;

    *value = parsed;
    return BE_OK;
}

int instrument_receive_int(instrument_t *inst, int *value, int timeout_ms) {
    if (!value)
        return BE_ERR_INVALID_PARAM;
    char buf[256];
    int n = instrument_receive(inst, buf, sizeof(buf), timeout_ms);
    if (n < 0)
        return n;

    char *end = NULL;
    long v = strtol(buf, &end, 10);
    if (end == buf || (*end != '\0' && *end != '\n' && *end != '\r'))
        return BE_ERR_PARSE;

    *value = (int)v;
    return BE_OK;
}
