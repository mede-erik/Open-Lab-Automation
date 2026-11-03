#include "platform.h"

static void _set_nonblocking(be_socket_t sock, bool nonblock) {
#ifdef _WIN32
    u_long mode = nonblock ? 1 : 0;
    ioctlsocket(sock, FIONBIO, &mode);
#else
    int flags = fcntl(sock, F_GETFL, 0);
    if (nonblock)
        fcntl(sock, F_SETFL, flags | O_NONBLOCK);
    else
        fcntl(sock, F_SETFL, flags & ~O_NONBLOCK);
#endif
}

int be_set_socket_timeout(be_socket_t sock, int timeout_ms) {
#ifdef _WIN32
    DWORD tv = timeout_ms;
#else
    struct timeval tv;
    tv.tv_sec = timeout_ms / 1000;
    tv.tv_usec = (timeout_ms % 1000) * 1000;
#endif
    if (setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, (const char *)&tv, sizeof(tv)) < 0)
        return BE_ERR_GENERAL;
    return BE_OK;
}

be_socket_t be_tcp_connect(const char *host, int port, int timeout_ms) {
    struct addrinfo hints, *result = NULL;
    char port_str[16];

    memset(&hints, 0, sizeof(hints));
    hints.ai_family = AF_UNSPEC;
    hints.ai_socktype = SOCK_STREAM;
    hints.ai_protocol = IPPROTO_TCP;

    snprintf(port_str, sizeof(port_str), "%d", port);

    int ret = getaddrinfo(host, port_str, &hints, &result);
    if (ret != 0 || result == NULL)
        return BE_INVALID_SOCKET;

    be_socket_t sock = BE_INVALID_SOCKET;
    for (struct addrinfo *rp = result; rp != NULL; rp = rp->ai_next) {
        sock = socket(rp->ai_family, rp->ai_socktype, rp->ai_protocol);
        if (sock == BE_INVALID_SOCKET)
            continue;

        _set_nonblocking(sock, true);

        connect(sock, rp->ai_addr, (be_socklen_t)rp->ai_addrlen);

        fd_set fdset;
        FD_ZERO(&fdset);
        FD_SET(sock, &fdset);

        struct timeval tv;
        tv.tv_sec = timeout_ms / 1000;
        tv.tv_usec = (timeout_ms % 1000) * 1000;

        if (select((int)sock + 1, NULL, &fdset, NULL, &tv) == 1) {
            int so_error = 0;
            be_socklen_t len = sizeof(so_error);
            if (getsockopt(sock, SOL_SOCKET, SO_ERROR, (char *)&so_error, &len) < 0)
                so_error = BE_GET_LAST_ERROR();
            if (so_error == 0) {
                _set_nonblocking(sock, false);
                freeaddrinfo(result);
                return sock;
            }
        }

        BE_CLOSE_SOCKET(sock);
        sock = BE_INVALID_SOCKET;
    }

    freeaddrinfo(result);
    return BE_INVALID_SOCKET;
}

int be_tcp_send(be_socket_t sock, const char *data, int len) {
    int total = 0;
    while (total < len) {
#ifdef MSG_NOSIGNAL
        /* avoid SIGPIPE killing the host (Python) process if the peer closed */
        int sent = (int)send(sock, data + total, len - total, MSG_NOSIGNAL);
#else
        int sent = (int)send(sock, data + total, len - total, 0);
#endif
        if (sent == BE_SOCKET_ERROR) {
#ifndef _WIN32
            if (errno == EINTR)
                continue;
#endif
            if (BE_GET_LAST_ERROR() == BE_EWOULDBLOCK) {
                BE_SLEEP_MS(10);
                continue;
            }
            return BE_ERR_SEND;
        }
        total += sent;
    }
    return total;
}

int be_tcp_recv(be_socket_t sock, char *buf, int buf_size, int timeout_ms) {
    be_set_socket_timeout(sock, timeout_ms);

    int total = 0;
    while (total < buf_size - 1) {
        int n = (int)recv(sock, buf + total, buf_size - 1 - total, 0);
        if (n == 0) {
            break;
        }
        if (n == BE_SOCKET_ERROR) {
#ifdef _WIN32
            int err = WSAGetLastError();
            if (err == WSAETIMEDOUT || err == WSAEWOULDBLOCK) {
                if (total > 0)
                    break;
                return BE_ERR_TIMEOUT;
            }
#else
            if (errno == EAGAIN || errno == EWOULDBLOCK) {
                if (total > 0)
                    break;
                return BE_ERR_TIMEOUT;
            }
            if (errno == EINTR)
                continue;
#endif
            return BE_ERR_RECV;
        }
        total += n;
        if (buf[total - 1] == '\n')
            break;
    }

    buf[total] = '\0';
    return total;
}

void be_tcp_close(be_socket_t sock) {
    if (sock != BE_INVALID_SOCKET) {
#ifdef _WIN32
        shutdown(sock, SD_BOTH);
#else
        shutdown(sock, SHUT_RDWR);
#endif
        BE_CLOSE_SOCKET(sock);
    }
}
