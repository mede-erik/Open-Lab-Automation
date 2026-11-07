// Copyright (C) 2025-2026 Erik Medeossi
// This file is part of Open Lab Automation.
// Licensed under the GNU General Public License v3.0; see the LICENSE file.

#ifndef PLATFORM_H
#define PLATFORM_H

#ifndef _WIN32
#define _POSIX_C_SOURCE 200112L
#define _GNU_SOURCE
#include <unistd.h>
#endif

#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdbool.h>

#ifdef _WIN32
    #include <winsock2.h>
    #include <ws2tcpip.h>
    #include <windows.h>
    typedef SOCKET be_socket_t;
    typedef int be_socklen_t;
    #define BE_INVALID_SOCKET INVALID_SOCKET
    #define BE_SOCKET_ERROR SOCKET_ERROR
    #define BE_CLOSE_SOCKET(s) closesocket(s)
    #define BE_GET_LAST_ERROR() WSAGetLastError()
    #define BE_EWOULDBLOCK WSAEWOULDBLOCK
    #define BE_ETIMEDOUT WSAETIMEDOUT
    #define BE_SLEEP_MS(ms) Sleep(ms)
#else
    #include <sys/socket.h>
    #include <netinet/in.h>
    #include <netinet/tcp.h>
    #include <netdb.h>
    #include <arpa/inet.h>
    #include <unistd.h>
    #include <errno.h>
    #include <time.h>
    #include <fcntl.h>
    typedef int be_socket_t;
    typedef socklen_t be_socklen_t;
    #define BE_INVALID_SOCKET (-1)
    #define BE_SOCKET_ERROR (-1)
    #define BE_CLOSE_SOCKET(s) close(s)
    #define BE_GET_LAST_ERROR() errno
    #define BE_EWOULDBLOCK EWOULDBLOCK
    #define BE_ETIMEDOUT ETIMEDOUT
    #include <time.h>
    static inline void be_sleep_ms(int ms) {
        struct timespec ts;
        ts.tv_sec = ms / 1000;
        ts.tv_nsec = (long)(ms % 1000) * 1000000L;
        nanosleep(&ts, NULL);
    }
    #define BE_SLEEP_MS(ms) be_sleep_ms(ms)
#endif

#include "backend.h"

#ifdef __cplusplus
extern "C" {
#endif

be_socket_t be_tcp_connect(const char *host, int port, int timeout_ms);
int be_tcp_send(be_socket_t sock, const char *data, int len);
int be_tcp_recv(be_socket_t sock, char *buf, int buf_size, int timeout_ms);
void be_tcp_close(be_socket_t sock);
int be_set_socket_timeout(be_socket_t sock, int timeout_ms);

#ifdef __cplusplus
}
#endif

#endif
