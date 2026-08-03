#!/bin/sh
# Build C backend as shared library
# Linux: gcc -shared -fPIC -o libbackend.so
# Windows (MinGW): gcc -shared -o backend.dll -lws2_32

set -e

cd "$(dirname "$0")"

UNAME_S=$(uname -s)
SRC="backend.c instrument.c platform.c sweep.c"
INCLUDE="-I."

echo "=== Building C Backend ==="

case "$UNAME_S" in
    Linux|Darwin)
        echo "Target: $UNAME_S (shared library)"
        gcc -shared -fPIC -o libbackend.so $SRC $INCLUDE -lm
        echo "Output: libbackend.so"
        ;;
    MINGW*|MSYS*|CYGWIN*)
        echo "Target: Windows (DLL)"
        gcc -shared -o backend.dll $SRC $INCLUDE -lm -lws2_32
        echo "Output: backend.dll"
        ;;
    *)
        echo "Unknown platform: $UNAME_S"
        echo "Trying Linux build..."
        gcc -shared -fPIC -o libbackend.so $SRC $INCLUDE -lm
        ;;
esac

echo "=== Build complete ==="
