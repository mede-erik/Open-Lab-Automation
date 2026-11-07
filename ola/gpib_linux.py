# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Linux set-up of a USB-GPIB adapter driven by linux-gpib (Keysight 82357B / 82357A, NI
GPIB-USB-HS).

A new Keysight 82357B does not work on Linux until several things are done as root:

1. **linux-gpib** is installed: the user part (``gpib_config``, ``libgpib``, the udev rules and the
   firmware loader) and, for kernels older than 6.13, the kernel modules (from 6.13 the drivers are
   in the kernel, ``drivers/staging/gpib``). From the distribution's package when there is one,
   otherwise built from the release tarball;
2. **fxload** and the **firmware**: the adapter starts as USB ``0957:0518`` and becomes
   ``0957:0718`` only after udev has loaded ``measat_releaseX1.8.hex`` with ``fxload -t fx2``
   (82357A: ``0957:0007``, ``82357a_fw.hex``), at every plug-in;
3. **/etc/gpib.conf** has an ``interface`` with ``minor = <board>`` and
   ``board_type = "agilent_82357a"`` (the same driver covers the 82357B);
4. the user is in the **gpib** group (``/dev/gpibN`` is ``0660 root:gpib``);
5. pyvisa-py reaches the board through **gpib-ctypes** (installed with pip, not as root).

``check_linux_setup`` looks at each step (``SetupStep``, with a translatable message);
``build_setup_script`` writes a bash script with only the steps that are missing;
``run_setup`` runs it as root with ``pkexec`` (the system asks for the administrator password) and
passes on its output line by line; ``install_python_bindings`` runs pip as the user. Everything that
touches the system goes through a ``SystemProbe`` or a ``runner``, replaced in the tests. No Qt.

Sources: the linux-gpib 4.3.7 README and the ``linux-gpib-user/usb`` files of its git repository
(``99-agilent_82357a.rules``, ``gpib_udev_fxloader``, ``98-gpib-generic.rules``).
"""

from __future__ import annotations

import getpass
import glob
import importlib.util
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .gpib_adapter import GpibAdapterConfig, GpibError, list_usb_devices, profile

LINUX_GPIB_VERSION = "4.3.7"
LINUX_GPIB_URL = (
    "https://sourceforge.net/projects/linux-gpib/files/"
    "linux-gpib%20for%203.x.x%20and%202.6.x%20kernels/{v}/linux-gpib-{v}.tar.gz/download"
).format(v=LINUX_GPIB_VERSION)
FIRMWARE_URL = "https://linux-gpib.sourceforge.io/firmware/gpib_firmware-2008-08-10.tar.gz"
IN_TREE_KERNEL = (6, 13)  # from this kernel the gpib drivers are part of Linux (staging)
FIRMWARE_DIRS = ("/usr/share/usb/agilent_82357a", "/usr/local/share/usb/agilent_82357a")
UDEV_DIRS = ("/etc/udev/rules.d", "/usr/lib/udev/rules.d", "/lib/udev/rules.d")
OUR_UDEV_RULE = "/etc/udev/rules.d/99-ola-agilent-82357.rules"
GPIB_CONF = "/etc/gpib.conf"
GPIB_GROUP = "gpib"


@dataclass(frozen=True)
class FirmwareInfo:
    """How udev turns an adapter without firmware into a working one."""

    file: str
    fxload_type: str  # fxload -t ...
    no_firmware_id: Tuple[int, int]
    ready_id: Tuple[int, int]


FIRMWARE: Dict[str, FirmwareInfo] = {
    "keysight_82357b": FirmwareInfo(
        "measat_releaseX1.8.hex", "fx2", (0x0957, 0x0518), (0x0957, 0x0718)
    ),
    "keysight_82357a": FirmwareInfo("82357a_fw.hex", "fx", (0x0957, 0x0007), (0x0957, 0x0107)),
}

# package manager: (refresh, install one package, "is it in the repositories?", build packages)
PACKAGE_MANAGERS: Dict[str, Dict[str, Any]] = {
    "apt": {
        "refresh": "apt-get update",
        "install": "DEBIAN_FRONTEND=noninteractive apt-get install -y",
        "query": "apt-cache show {pkg} >/dev/null 2>&1",
        "build": [
            "build-essential",
            "linux-headers-$(uname -r)",
            "autoconf",
            "automake",
            "libtool",
            "bison",
            "flex",
            "curl",
            "tar",
        ],
    },
    "dnf": {
        "refresh": "",
        "install": "dnf install -y",
        "query": "dnf info {pkg} >/dev/null 2>&1",
        "build": [
            "gcc",
            "make",
            "kernel-devel-$(uname -r)",
            "autoconf",
            "automake",
            "libtool",
            "bison",
            "flex",
            "curl",
            "tar",
        ],
    },
    "pacman": {
        "refresh": "pacman -Sy",
        "install": "pacman -S --noconfirm --needed",
        "query": "pacman -Si {pkg} >/dev/null 2>&1",
        "build": [
            "base-devel",
            "linux-headers",
            "autoconf",
            "automake",
            "libtool",
            "bison",
            "flex",
            "curl",
            "tar",
        ],
    },
    "zypper": {
        "refresh": "zypper --non-interactive refresh",
        "install": "zypper --non-interactive install",
        "query": "zypper --non-interactive info {pkg} 2>/dev/null | grep -q '^Name'",
        "build": [
            "gcc",
            "make",
            "kernel-devel",
            "autoconf",
            "automake",
            "libtool",
            "bison",
            "flex",
            "curl",
            "tar",
        ],
    },
}
_DISTRO_MANAGER = {
    "debian": "apt",
    "ubuntu": "apt",
    "linuxmint": "apt",
    "pop": "apt",
    "raspbian": "apt",
    "fedora": "dnf",
    "rhel": "dnf",
    "centos": "dnf",
    "rocky": "dnf",
    "almalinux": "dnf",
    "arch": "pacman",
    "manjaro": "pacman",
    "endeavouros": "pacman",
    "opensuse": "zypper",
    "suse": "zypper",
    "opensuse-leap": "zypper",
    "opensuse-tumbleweed": "zypper",
    "sles": "zypper",
}

MESSAGES: Dict[str, str] = {
    "lx_distro": "Distribution: {name} (packages: {manager})",
    "lx_distro_unknown": "Distribution {name} not recognised: install the packages by hand "
    "(compiler, kernel headers, autotools, bison, flex, fxload)",
    "lx_build_ok": "Compiler and kernel headers present",
    "lx_build_missing": "Missing to build linux-gpib: {missing}",
    "lx_user_ok": "linux-gpib installed ({path})",
    "lx_user_missing": "linux-gpib is not installed (gpib_config, libgpib)",
    "lx_module_ok": "Kernel module agilent_82357a available (loaded: {loaded})",
    "lx_module_missing": "Kernel module agilent_82357a missing for kernel {kernel}: it will be "
    "built from linux-gpib",
    "lx_module_missing_intree": "Kernel module agilent_82357a missing: kernel {kernel} has the "
    "gpib drivers in staging, but this distribution does not build them (CONFIG_GPIB)",
    "lx_secure_boot": "[GPIB-009] Secure Boot is on: a kernel module built here is not signed and "
    "will not load (sign it with mokutil or turn Secure Boot off)",
    "lx_secure_boot_off": "Secure Boot is off",
    "lx_fxload_ok": "fxload present ({path})",
    "lx_fxload_missing": "fxload missing: it loads the adapter's firmware",
    "lx_firmware_ok": "Firmware {file} present in {dir}",
    "lx_firmware_missing": "Firmware {file} missing (it goes in {dir})",
    "lx_udev_ok": "udev rule that loads the firmware present ({path})",
    "lx_udev_missing": "No udev rule loads the firmware when the adapter is plugged in",
    "lx_conf_ok": "{conf}: interface minor {minor} = {board_type}",
    "lx_conf_missing": "{conf} has no interface minor {minor} with board_type {board_type}",
    "lx_group_ok": "User {user} is in the {group} group",
    "lx_group_relogin": "User {user} has been added to the {group} group: log out and back in",
    "lx_group_missing": "User {user} is not in the {group} group (needed for {device})",
    "lx_usb_ready": "Adapter connected with firmware loaded ({ids})",
    "lx_usb_no_firmware": "Adapter connected but without firmware ({ids}): after the set-up "
    "unplug it and plug it in again",
    "lx_usb_absent": "Adapter not connected: plug it in",
    "lx_usb_unknown": "USB devices cannot be listed: adapter check skipped",
    "lx_dev_ok": "{device} present and usable",
    "lx_dev_no_access": "{device} present but not readable/writable by {user}",
    "lx_dev_missing": "{device} does not exist yet (module not loaded or board not configured)",
    "lx_python_ok": "Python bindings for GPIB installed ({module})",
    "lx_python_missing": "Python bindings for GPIB missing: gpib-ctypes (installed with pip, "
    "no administrator password)",
    "lx_pyvisa_ok": "pyvisa-py sees GPIB{board}::INTFC",
    "lx_pyvisa_missing": "pyvisa-py does not see GPIB{board}::INTFC yet",
    "lx_not_needed": "Nothing to do as administrator",
    "lx_no_pkexec": "[GPIB-008] pkexec is not available: run the script as administrator with: "
    "sudo bash {script}",
    "lx_failed": "[GPIB-008] the set-up stopped with exit code {code}: read the log",
}

OK, MISSING, WARN, INFO = "ok", "missing", "warn", "info"


@dataclass
class SetupStep:
    """One step of the set-up and its state; ``fix`` names the part of the script that does it
    ("" if the step is only a check), ``root`` whether that part needs the administrator."""

    id: str
    status: str
    key: str
    values: Dict[str, Any] = field(default_factory=dict)
    fix: str = ""
    root: bool = True

    @property
    def text(self) -> str:
        """The message in English, with its values."""
        return MESSAGES[self.key].format(**self.values)

    @property
    def needs_fix(self) -> bool:
        """True when the step is not done and the set-up can do it."""
        return self.status == MISSING and bool(self.fix)


@dataclass
class LinuxSetupReport:
    """The state of the system for one adapter (see ``check_linux_setup``)."""

    config: GpibAdapterConfig
    steps: List[SetupStep]
    manager: Optional[str]
    kernel: str
    user: str
    gpib_conf: str
    """The current text of /etc/gpib.conf ('' if there is none)."""

    def step(self, step_id: str) -> Optional[SetupStep]:
        """The step ``step_id`` (None if it was not checked)."""
        return next((s for s in self.steps if s.id == step_id), None)

    @property
    def root_fixes(self) -> List[str]:
        """The parts of the script needed, in order (empty: nothing to do as administrator)."""
        wanted = {s.fix for s in self.steps if s.needs_fix and s.root}
        if wanted & {"linux_gpib", "firmware", "udev"}:
            wanted.add("packages")
        return [f for f in ROOT_FIXES if f in wanted]

    @property
    def needs_python(self) -> bool:
        """True when the Python bindings must be installed (with pip, as the user)."""
        return any(s.needs_fix and s.fix == "python" for s in self.steps)


ROOT_FIXES = ("packages", "linux_gpib", "firmware", "udev", "gpib_conf", "group")


# ----- the system ------------------------------------------------------------------------------
class SystemProbe:
    """Read-only look at the system (every method is replaced in the tests)."""

    platform = sys.platform

    def read_text(self, path: str) -> Optional[str]:
        """The text of ``path`` (None if it cannot be read)."""
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                return f.read()
        except OSError:
            return None

    def exists(self, path: str) -> bool:
        """True if ``path`` exists."""
        return os.path.exists(path)

    def access_rw(self, path: str) -> bool:
        """True if the user can read and write ``path``."""
        return os.access(path, os.R_OK | os.W_OK)

    def which(self, command: str) -> Optional[str]:
        """Full path of ``command`` (also in the sbin folders, often not in a user's PATH)."""
        found = shutil.which(command)
        if found:
            return found
        for folder in ("/usr/local/sbin", "/usr/sbin", "/sbin"):
            path = os.path.join(folder, command)
            if os.access(path, os.X_OK):
                return path
        return None

    def run(self, argv: Sequence[str], timeout: float = 10) -> Tuple[int, str]:
        """Run a read-only command: (exit code, output); 127 if it does not exist."""
        try:
            done = subprocess.run(
                list(argv), capture_output=True, text=True, timeout=timeout, check=False
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return 127, str(exc)
        return done.returncode, (done.stdout or "") + (done.stderr or "")

    def glob(self, pattern: str) -> List[str]:
        """Paths that match ``pattern``."""
        return sorted(glob.glob(pattern))

    def usb_devices(self) -> Optional[List[Tuple[int, int]]]:
        """(vendor, product) of the USB devices, None if they cannot be listed."""
        return list_usb_devices()

    def kernel_release(self) -> str:
        """``uname -r``."""
        return os.uname().release if hasattr(os, "uname") else ""

    def user(self) -> str:
        """The user running the program."""
        return getpass.getuser()

    def group_members(self, group: str) -> Optional[List[str]]:
        """Members of ``group`` in /etc/group (None if the group does not exist)."""
        try:
            import grp

            return list(grp.getgrnam(group).gr_mem)
        except (ImportError, KeyError):
            return None

    def session_groups(self) -> List[str]:
        """Groups of the running session (a group added later counts after a new login)."""
        try:
            import grp

            return [grp.getgrgid(g).gr_name for g in os.getgroups()]
        except (ImportError, KeyError, OSError):
            return []

    def find_spec(self, module: str) -> bool:
        """True if the Python module ``module`` can be imported."""
        try:
            return importlib.util.find_spec(module) is not None
        except (ImportError, ValueError):
            return False


def kernel_version(release: str) -> Tuple[int, int]:
    """``'6.8.0-45-generic'`` -> ``(6, 8)`` (``(0, 0)`` if not readable)."""
    m = re.match(r"(\d+)\.(\d+)", release or "")
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def os_release(probe: SystemProbe) -> Dict[str, str]:
    """The fields of /etc/os-release."""
    out = {}
    for line in (probe.read_text("/etc/os-release") or "").splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            out[key.strip()] = value.strip().strip('"')
    return out


def package_manager(release: Dict[str, str]) -> Optional[str]:
    """apt / dnf / pacman / zypper for the distribution of ``release`` (None if unknown)."""
    ids = [release.get("ID", "")] + release.get("ID_LIKE", "").split()
    for distro in ids:
        manager = _DISTRO_MANAGER.get(distro.lower())
        if manager:
            return manager
    return None


# ----- /etc/gpib.conf ---------------------------------------------------------------------------
_BLOCK = re.compile(r"interface\s*\{(?P<body>.*?)\}", re.S)


def _strip_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def _field(body: str, name: str) -> Optional[str]:
    m = re.search(rf"(?m)^\s*{re.escape(name)}\s*=\s*\"?([^\"\s;]+)\"?", _strip_comments(body))
    return m.group(1) if m else None


def find_interface(text: str, minor: int) -> Optional[Dict[str, str]]:
    """The ``interface`` block of gpib.conf with ``minor`` (its board_type and name), or None."""
    for m in _BLOCK.finditer(_strip_comments(text or "")):
        body = m.group("body")
        if _field(body, "minor") == str(minor):
            return {
                "board_type": _field(body, "board_type") or "",
                "name": _field(body, "name") or "",
            }
    return None


def interface_block(minor: int, board_type: str) -> str:
    """An ``interface`` block of gpib.conf for a USB adapter (fields of the linux-gpib template)."""
    return (
        "interface {\n"
        f"\tminor = {minor}\t/* /dev/gpib{minor} */\n"
        f'\tboard_type = "{board_type}"\n'
        f'\tname = "gpib{minor}"\n'
        "\tpad = 0\t/* primary address of the adapter (controller) */\n"
        "\tsad = 0\n"
        "\ttimeout = T3s\n"
        "\teos = 0x0a\n"
        "\tset-reos = yes\n"
        "\tset-bin = no\n"
        "\tset-xeos = no\n"
        "\tset-eot = yes\n"
        "\tmaster = yes\n"
        "}\n"
    )


def gpib_conf_text(existing: str, minor: int, board_type: str) -> str:
    """``existing`` (the current gpib.conf, '' if none) with the ``interface`` of ``minor``
    replaced by one for ``board_type``; the other interfaces and the ``device`` blocks are kept."""
    existing = existing or ""
    out, pos, replaced = [], 0, False
    for m in re.finditer(r"interface\s*\{.*?\}\s*", existing, re.S):
        if _field(m.group(0), "minor") == str(minor):
            out.append(existing[pos : m.start()])
            out.append(interface_block(minor, board_type) + "\n")
            pos, replaced = m.end(), True
    out.append(existing[pos:])
    text = "".join(out)
    if not replaced:
        header = (
            "" if text.strip() else "/* written by Open Lab Automation (Tools > GPIB adapters) */\n"
        )
        text = (
            header
            + text.rstrip()
            + ("\n\n" if text.strip() else "")
            + interface_block(minor, board_type)
        )
    return text


def udev_rule_text(profile_id: str, minor: int) -> str:
    """Our udev rule, used only when linux-gpib did not install its own: load the firmware when the
    adapter appears without it, configure the board when it comes back with it, and give
    /dev/gpibN to the gpib group. ``@FXLOAD@``, ``@FIRMWARE_DIR@`` and ``@GPIB_CONFIG@`` are filled
    in by the script with the paths found on the system."""
    fw = FIRMWARE[profile_id]
    vid, raw = fw.no_firmware_id
    ready = fw.ready_id[1]
    return (
        "# Open Lab Automation: firmware and configuration of the "
        f"{profile(profile_id).name}\n"
        f'ACTION=="add", SUBSYSTEM=="usb", ATTR{{idVendor}}=="{vid:04x}", '
        f'ATTR{{idProduct}}=="{raw:04x}", '
        f'RUN+="@FXLOAD@ -t {fw.fxload_type} -D $env{{DEVNAME}} -I @FIRMWARE_DIR@/{fw.file}"\n'
        f'ACTION=="add", SUBSYSTEM=="usb", ATTR{{idVendor}}=="{vid:04x}", '
        f'ATTR{{idProduct}}=="{ready:04x}", RUN+="@GPIB_CONFIG@ --minor {minor}"\n'
        f'KERNEL=="gpib[0-9]*", MODE="0660", GROUP="{GPIB_GROUP}"\n'
    )


# ----- check -------------------------------------------------------------------------------------
def supports_linux_setup(config: GpibAdapterConfig, platform: str = sys.platform) -> bool:
    """True on Linux for an adapter driven by linux-gpib."""
    return platform.startswith("linux") and bool(profile(config.profile).linux_driver)


def check_linux_setup(
    config: GpibAdapterConfig, probe: Optional[SystemProbe] = None, rm_factory=None
) -> LinuxSetupReport:
    """Check each step of the Linux set-up of the adapter of ``config`` (see the module docstring).
    ``rm_factory(backend)`` replaces ``pyvisa.ResourceManager`` for the last step."""
    probe = probe or SystemProbe()
    prof = profile(config.profile)
    driver = prof.linux_driver
    fw = FIRMWARE.get(config.profile)
    minor = config.board
    device = f"/dev/gpib{minor}"
    user = probe.user()
    kernel = probe.kernel_release()
    steps: List[SetupStep] = []

    release = os_release(probe)
    manager = package_manager(release)
    name = release.get("PRETTY_NAME") or release.get("ID") or "?"
    if manager:
        steps.append(SetupStep("distro", INFO, "lx_distro", {"name": name, "manager": manager}))
    else:
        steps.append(SetupStep("distro", WARN, "lx_distro_unknown", {"name": name}))

    gpib_config = probe.which("gpib_config")
    libs = [
        p
        for pattern in (
            "/usr/lib*/libgpib.so*",
            "/usr/local/lib*/libgpib.so*",
            "/usr/lib/*/libgpib.so*",
        )
        for p in probe.glob(pattern)
    ]
    user_ok = bool(gpib_config and libs)
    rc, _ = probe.run(["modinfo", driver])
    module_ok = rc == 0
    in_tree = kernel_version(kernel) >= IN_TREE_KERNEL

    if not user_ok or (not module_ok and not in_tree):
        missing = [c for c in ("gcc", "make") if not probe.which(c)]
        if not module_ok and not in_tree and not probe.exists(f"/lib/modules/{kernel}/build"):
            missing.append(f"kernel headers {kernel}")
        if missing:
            steps.append(
                SetupStep(
                    "build_tools",
                    MISSING,
                    "lx_build_missing",
                    {"missing": ", ".join(missing)},
                    fix="packages",
                )
            )
        else:
            steps.append(SetupStep("build_tools", OK, "lx_build_ok"))

    if user_ok:
        steps.append(SetupStep("linux_gpib_user", OK, "lx_user_ok", {"path": gpib_config}))
    else:
        steps.append(SetupStep("linux_gpib_user", MISSING, "lx_user_missing", fix="linux_gpib"))

    if module_ok:
        loaded = "yes" if probe.exists(f"/sys/module/{driver}") else "no"
        steps.append(SetupStep("kernel_module", OK, "lx_module_ok", {"loaded": loaded}))
    elif in_tree:
        steps.append(
            SetupStep("kernel_module", WARN, "lx_module_missing_intree", {"kernel": kernel})
        )
    else:
        steps.append(
            SetupStep(
                "kernel_module", MISSING, "lx_module_missing", {"kernel": kernel}, fix="linux_gpib"
            )
        )
        rc, out = probe.run(["mokutil", "--sb-state"])
        if rc == 0 and "enabled" in out.lower():
            steps.append(SetupStep("secure_boot", WARN, "lx_secure_boot"))
        elif rc == 0:
            steps.append(SetupStep("secure_boot", OK, "lx_secure_boot_off"))

    if fw is not None:
        fxload = probe.which("fxload")
        if fxload:
            steps.append(SetupStep("fxload", OK, "lx_fxload_ok", {"path": fxload}))
        else:
            steps.append(SetupStep("fxload", MISSING, "lx_fxload_missing", fix="packages"))
        where = next((d for d in FIRMWARE_DIRS if probe.exists(f"{d}/{fw.file}")), None)
        if where:
            steps.append(
                SetupStep("firmware", OK, "lx_firmware_ok", {"file": fw.file, "dir": where})
            )
        else:
            steps.append(
                SetupStep(
                    "firmware",
                    MISSING,
                    "lx_firmware_missing",
                    {"file": fw.file, "dir": FIRMWARE_DIRS[0]},
                    fix="firmware",
                )
            )
        rules = [p for d in UDEV_DIRS for p in probe.glob(f"{d}/*82357*.rules")]
        if rules:
            steps.append(SetupStep("udev_rule", OK, "lx_udev_ok", {"path": rules[0]}))
        else:
            steps.append(SetupStep("udev_rule", MISSING, "lx_udev_missing", fix="udev"))

    conf = probe.read_text(GPIB_CONF) or ""
    block = find_interface(conf, minor)
    values = {"conf": GPIB_CONF, "minor": minor, "board_type": driver}
    if block and block["board_type"] == driver:
        steps.append(SetupStep("gpib_conf", OK, "lx_conf_ok", values))
    else:
        steps.append(SetupStep("gpib_conf", MISSING, "lx_conf_missing", values, fix="gpib_conf"))

    members = probe.group_members(GPIB_GROUP)
    gvalues = {"user": user, "group": GPIB_GROUP, "device": device}
    if GPIB_GROUP in probe.session_groups():
        steps.append(SetupStep("gpib_group", OK, "lx_group_ok", gvalues))
    elif members is not None and user in members:
        steps.append(SetupStep("gpib_group", WARN, "lx_group_relogin", gvalues))
    else:
        steps.append(SetupStep("gpib_group", MISSING, "lx_group_missing", gvalues, fix="group"))

    usb = probe.usb_devices()
    if fw is not None:
        ready = [i for i in prof.usb_ids if usb and i in usb]
        raw = [i for i in prof.no_firmware_ids if usb and i in usb]
        ids = lambda found: ", ".join(f"{v:04x}:{p:04x}" for v, p in found)  # noqa: E731
        if usb is None:
            steps.append(SetupStep("usb_state", INFO, "lx_usb_unknown"))
        elif ready:
            steps.append(SetupStep("usb_state", OK, "lx_usb_ready", {"ids": ids(ready)}))
        elif raw:
            steps.append(SetupStep("usb_state", WARN, "lx_usb_no_firmware", {"ids": ids(raw)}))
        else:
            steps.append(SetupStep("usb_state", WARN, "lx_usb_absent"))

    if probe.exists(device):
        if probe.access_rw(device):
            steps.append(SetupStep("dev_node", OK, "lx_dev_ok", {"device": device}))
        else:
            steps.append(
                SetupStep("dev_node", WARN, "lx_dev_no_access", {"device": device, "user": user})
            )
    else:
        steps.append(SetupStep("dev_node", WARN, "lx_dev_missing", {"device": device}))

    module = next((m for m in ("gpib_ctypes", "gpib") if probe.find_spec(m)), None)
    if module:
        steps.append(
            SetupStep("python_bindings", OK, "lx_python_ok", {"module": module}, root=False)
        )
    else:
        steps.append(
            SetupStep("python_bindings", MISSING, "lx_python_missing", fix="python", root=False)
        )

    if rm_factory is not None:
        from .gpib_adapter import _boards

        try:
            boards = _boards(rm_factory("@py"))
        except Exception:  # pyvisa-py not installed or not working
            boards = []
        seen = any(b.upper() == f"GPIB{minor}::INTFC" for b in boards)
        steps.append(
            SetupStep(
                "pyvisa_board",
                OK if seen else WARN,
                "lx_pyvisa_ok" if seen else "lx_pyvisa_missing",
                {"board": minor},
                root=False,
            )
        )
    return LinuxSetupReport(config, steps, manager, kernel, user, conf)


# ----- the script --------------------------------------------------------------------------------
def _heredoc(path: str, text: str, mode: str = "0644") -> str:
    marker = "OLA_EOF"
    while marker in text:
        marker += "_"
    return f"cat > {path} <<'{marker}'\n{text.rstrip()}\n{marker}\nchmod {mode} {path}\n"


def build_setup_script(report: LinuxSetupReport, firmware_dir: str = "") -> str:
    """The bash script that does, as root, the steps of ``report`` that are missing ('' if none).
    ``firmware_dir``: a folder that already holds the firmware files (otherwise they are
    downloaded from the linux-gpib site)."""
    fixes = report.root_fixes
    if not fixes:
        return ""
    cfg = report.config
    prof = profile(cfg.profile)
    driver = prof.linux_driver
    fw = FIRMWARE.get(cfg.profile)
    pm = PACKAGE_MANAGERS.get(report.manager or "")
    q = shlex.quote
    lines = [
        "#!/bin/bash",
        f"# Open Lab Automation: Linux set-up of '{cfg.name}' ({prof.name}), board GPIB{cfg.board}",
        "# Generated by Tools > GPIB adapters. Run as root (pkexec or sudo). Safe to run again.",
        "set -euo pipefail",
        f"LINUX_GPIB_VERSION={LINUX_GPIB_VERSION}",
        f"LINUX_GPIB_URL={q(LINUX_GPIB_URL)}",
        f"FIRMWARE_URL={q(FIRMWARE_URL)}",
        f"FIRMWARE_SRC={q(firmware_dir)}",
        f"TARGET_USER={q(report.user)}",
        f"MINOR={cfg.board}",
        f"DRIVER={driver}",
        "WORK=$(mktemp -d /tmp/ola-gpib.XXXXXX)",
        "trap 'rm -rf \"$WORK\"' EXIT",
        'step() { echo; echo "==> $*"; }',
        'ver_lt() { [ "$1" != "$2" ] && '
        '[ "$(printf \'%s\\n%s\\n\' "$1" "$2" | sort -V | head -n1)" = "$1" ]; }',
        'find_cmd() { command -v "$1" 2>/dev/null || for d in /usr/local/sbin /usr/sbin /sbin; do '
        '[ -x "$d/$1" ] && { echo "$d/$1"; return 0; }; done; return 1; }',
        "",
    ]
    if pm:
        install, query = pm["install"], pm["query"].format(pkg='"$1"')
        lines += [
            'pkg_install() { for p in "$@"; do',
            f'  {install} "$p" || echo "!! package $p not installed"',
            "done; }",
            f"pkg_available() {{ {query}; }}",
        ]
    else:
        lines += [
            'pkg_install() { echo "!! unknown distribution: install by hand: $*"; }',
            "pkg_available() { return 1; }",
        ]
    lines.append("")

    if "packages" in fixes:
        packages = list(pm["build"]) if pm else []
        if fw is not None:
            packages.append("fxload")
        lines.append('step "Packages: compiler, kernel headers, autotools, fxload"')
        if pm and pm["refresh"]:
            lines.append(f"{pm['refresh']} || true")
        lines.append("pkg_install " + " ".join(packages))
        lines.append("")

    if "linux_gpib" in fixes:
        lines += [
            'step "linux-gpib $LINUX_GPIB_VERSION"',
            'if ! find_cmd gpib_config >/dev/null || ! modinfo "$DRIVER" >/dev/null 2>&1; then',
            "  if pkg_available linux-gpib; then",
            '    echo "linux-gpib package of the distribution"',
            "    pkg_install linux-gpib",
            "  fi",
            "fi",
            'if ! find_cmd gpib_config >/dev/null || ! modinfo "$DRIVER" >/dev/null 2>&1; then',
            '  echo "building linux-gpib from the release tarball"',
            '  curl -fL --retry 3 -o "$WORK/linux-gpib.tar.gz" "$LINUX_GPIB_URL"',
            '  tar -xzf "$WORK/linux-gpib.tar.gz" -C "$WORK"',
            '  SRC=$(dirname "$(find "$WORK" -name "linux-gpib-user-*.tar.gz" | head -n1)")',
            "  KREL=$(uname -r)",
            '  if ! modinfo "$DRIVER" >/dev/null 2>&1; then',
            '    if ver_lt "${KREL%%-*}" "6.13"; then',
            '      tar -xzf "$SRC"/linux-gpib-kernel-*.tar.gz -C "$WORK"',
            '      cd "$WORK"/linux-gpib-kernel-*/',
            '      make -j"$(nproc)"',
            '      rm -rf "/lib/modules/$KREL/gpib"',
            "      make install",
            "      depmod -a",
            "    else",
            '      echo "!! kernel $KREL has the gpib drivers in staging, but this"',
            '      echo "!! distribution does not build them (CONFIG_GPIB):"',
            '      echo "!! install a kernel with them, then run again"',
            "    fi",
            "  fi",
            "  if ! find_cmd gpib_config >/dev/null; then",
            '    tar -xzf "$SRC"/linux-gpib-user-*.tar.gz -C "$WORK"',
            '    cd "$WORK"/linux-gpib-user-*/',
            "    ./configure --sysconfdir=/etc",
            '    make -j"$(nproc)"',
            "    make install",
            "    ldconfig",
            "  fi",
            "fi",
            "",
        ]

    if fw is not None and "firmware" in fixes:
        lines += [
            f'step "Firmware {fw.file}"',
            f"FW_FILE={fw.file}",
            'if [ -n "$FIRMWARE_SRC" ] && [ -f "$FIRMWARE_SRC/$FW_FILE" ]; then',
            '  FW_FOUND="$FIRMWARE_SRC/$FW_FILE"',
            "else",
            '  curl -fL --retry 3 -o "$WORK/firmware.tar.gz" "$FIRMWARE_URL" || {',
            '    echo "!! cannot download $FIRMWARE_URL: put $FW_FILE in a folder,"',
            '    echo "!! choose it in Tools > GPIB adapters > Linux set-up (Firmware folder)"',
            '    echo "!! and run again"; exit 3; }',
            '  tar -xzf "$WORK/firmware.tar.gz" -C "$WORK"',
            '  FW_FOUND=$(find "$WORK" -name "$FW_FILE" | head -n1)',
            '  [ -n "$FW_FOUND" ] || {',
            '    echo "!! $FW_FILE is not in the firmware archive"; exit 3; }',
            "fi",
            "FW_DIRS=()",
            f"for d in {' '.join(FIRMWARE_DIRS)}; do",
            '  if [ -d "$d" ]; then FW_DIRS+=("$d"); fi',
            "done",
            "[ ${#FW_DIRS[@]} -gt 0 ] || FW_DIRS=(/usr/share/usb/agilent_82357a)",
            'for d in "${FW_DIRS[@]}"; do',
            '  mkdir -p "$d"; cp -f "$FW_FOUND" "$d/"; chmod 0644 "$d/$FW_FILE"',
            '  if [ -n "$FIRMWARE_SRC" ]; then',
            '    cp -f "$FIRMWARE_SRC"/*.hex "$d/" 2>/dev/null || true',
            "  fi",
            '  echo "firmware in $d"',
            "done",
            "",
        ]

    if fw is not None and ("udev" in fixes or "linux_gpib" in fixes):
        rule = udev_rule_text(cfg.profile, cfg.board)
        lines += [
            'step "udev rule (firmware at every plug-in)"',
            "if ls "
            + " ".join(f"{d}/*82357a*.rules" for d in UDEV_DIRS)
            + " >/dev/null 2>&1; then",
            '  echo "the udev rules of linux-gpib are installed"',
            "else",
            "  FXLOAD=$(find_cmd fxload || echo /sbin/fxload)",
            "  GPIBCFG=$(find_cmd gpib_config || echo /usr/local/sbin/gpib_config)",
            "  FWDIR=" + FIRMWARE_DIRS[0],
            f"  [ -f {FIRMWARE_DIRS[1]}/{fw.file} ] && FWDIR={FIRMWARE_DIRS[1]}",
            _heredoc(OUR_UDEV_RULE, rule).rstrip(),  # not indented: the heredoc end marker
            '  sed -i "s|@FXLOAD@|$FXLOAD|; s|@FIRMWARE_DIR@|$FWDIR|; s|@GPIB_CONFIG@|$GPIBCFG|" '
            + OUR_UDEV_RULE,
            "fi",
            "",
        ]

    if "gpib_conf" in fixes:
        text = gpib_conf_text(report.gpib_conf, cfg.board, driver)
        lines += [
            f'step "{GPIB_CONF}: interface minor $MINOR = $DRIVER"',
            f"[ -f {GPIB_CONF} ] && "
            f'cp -p {GPIB_CONF} "{GPIB_CONF}.ola-backup-$(date +%Y%m%d%H%M%S)"',
            _heredoc(GPIB_CONF, text).rstrip(),
            "",
        ]

    if "group" in fixes:
        lines += [
            f'step "Group {GPIB_GROUP} for $TARGET_USER"',
            f"groupadd -f {GPIB_GROUP}",
            f'usermod -aG {GPIB_GROUP} "$TARGET_USER"',
            "",
        ]

    lines += [
        'step "Load the driver and apply the udev rules"',
        "udevadm control --reload-rules || true",
        "udevadm trigger --subsystem-match=usb --attr-match=idVendor=0957 || true",
        'modprobe "$DRIVER" || echo "!! modprobe $DRIVER failed (see Secure Boot / kernel)"',
        "sleep 3",
        'if [ -e "/dev/gpib$MINOR" ] && GPIBCFG=$(find_cmd gpib_config); then',
        '  "$GPIBCFG" --minor "$MINOR" ||',
        '    echo "!! gpib_config failed: unplug the adapter and plug it in again"',
        "fi",
        'echo; echo "Done. Unplug the adapter and plug it in again;"',
        'echo "log out and back in if you were added to the gpib group."',
    ]
    return "\n".join(lines) + "\n"


# ----- running -----------------------------------------------------------------------------------
Runner = Callable[[Sequence[str], Callable[[str], None]], int]


def default_runner(argv: Sequence[str], on_output: Callable[[str], None]) -> int:
    """Run ``argv`` and pass each line of its output to ``on_output``; the exit code."""
    proc = subprocess.Popen(
        list(argv), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        on_output(line.rstrip("\n"))
    return proc.wait()


def write_script(script: str, folder: Optional[str] = None) -> str:
    """Save the script in a file only the user can change; its path."""
    fd, path = tempfile.mkstemp(prefix="ola-gpib-setup-", suffix=".sh", dir=folder)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(script)
    os.chmod(path, 0o700)
    return path


def run_setup(
    script: str,
    on_output: Callable[[str], None] = lambda line: None,
    runner: Runner = default_runner,
    which: Optional[Callable[[str], Optional[str]]] = None,
    folder: Optional[str] = None,
) -> int:
    """Run ``script`` as root with ``pkexec`` (the system asks for the password). ``GpibError``
    [GPIB-008] if pkexec is missing (the message gives the sudo command) or the script fails."""
    path = write_script(script, folder)
    pkexec = (which or shutil.which)("pkexec")
    if not pkexec:
        raise GpibError(MESSAGES["lx_no_pkexec"].format(script=path))
    code = runner([pkexec, "/bin/bash", path], on_output)
    if code != 0:
        raise GpibError(MESSAGES["lx_failed"].format(code=code))
    try:
        os.unlink(path)
    except OSError:
        pass
    return code


def install_python_bindings(
    on_output: Callable[[str], None] = lambda line: None, runner: Runner = default_runner
) -> int:
    """``pip install gpib-ctypes`` for this Python, as the user. ``GpibError`` [GPIB-008] if it
    fails."""
    code = runner([sys.executable, "-m", "pip", "install", "gpib-ctypes"], on_output)
    if code != 0:
        raise GpibError(MESSAGES["lx_failed"].format(code=code))
    return code


__all__ = [
    "FIRMWARE",
    "LINUX_GPIB_VERSION",
    "LinuxSetupReport",
    "MESSAGES",
    "SetupStep",
    "SystemProbe",
    "build_setup_script",
    "check_linux_setup",
    "find_interface",
    "gpib_conf_text",
    "install_python_bindings",
    "interface_block",
    "kernel_version",
    "package_manager",
    "run_setup",
    "supports_linux_setup",
    "udev_rule_text",
]
