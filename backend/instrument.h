#ifndef INSTRUMENT_H
#define INSTRUMENT_H

#include "platform.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    be_socket_t socket;
    char host[64];
    int port;
    bool connected;
} instrument_t;

int instrument_pool_init(void);
void instrument_pool_cleanup(void);
int instrument_pool_connect(be_instr_t *handle, const char *host, int port, int timeout_ms);
int instrument_pool_disconnect(be_instr_t handle);
instrument_t *instrument_pool_get(be_instr_t handle);
int instrument_send(instrument_t *inst, const char *command);
int instrument_receive(instrument_t *inst, char *buffer, int buf_size, int timeout_ms);
int instrument_receive_float(instrument_t *inst, double *value, int timeout_ms);
int instrument_receive_int(instrument_t *inst, int *value, int timeout_ms);

#ifdef __cplusplus
}
#endif

#endif
