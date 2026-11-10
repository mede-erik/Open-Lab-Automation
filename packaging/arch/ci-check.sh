#!/bin/bash
# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

# Used by the CI (job "arch"), inside an archlinux:base-devel container: builds the PKGBUILD of
# this folder at the commit given in $1, installs the package and checks that the program starts.
# makepkg refuses to run as root, so the build is done by a throw-away user.
#
#   packaging/arch/ci-check.sh <commit>

set -euo pipefail
commit="${1:?usage: ci-check.sh <commit>}"
repo="$(cd "$(dirname "$0")/../.." && pwd)"

pacman -Syu --noconfirm --needed git sudo
useradd --create-home builder
echo 'builder ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/builder

# The PKGBUILD clones the repository: give it a local copy of this checkout, at the commit
cp -r "$repo" /home/builder/src
chown -R builder:builder /home/builder/src
sudo -u builder git config --global --add safe.directory '*'
sudo -u builder git config --global url."file:///home/builder/src/".insteadOf "https://github.com/mede-erik/Open-Lab-Automation.git"

cd /home/builder/src/packaging/arch
sudo -u builder env OLA_FRAGMENT="commit=${commit}" makepkg --syncdeps --noconfirm --cleanbuild

pacman -U --noconfirm ./*.pkg.tar.zst
# sed, not head: with pipefail, head closing the pipe early would make pacman fail with SIGPIPE
pacman -Ql open-lab-automation | sed -n '1,20p'

# The program must start (offscreen) and keep running until the timeout kills it (exit code 124)
set +e
QT_QPA_PLATFORM=offscreen HOME=/tmp/ola-home timeout 15 open-lab-automation
code=$?
set -e
if [ "$code" -ne 124 ]; then
    echo "open-lab-automation exited with code $code instead of running" >&2
    exit 1
fi
echo "Arch package OK"
