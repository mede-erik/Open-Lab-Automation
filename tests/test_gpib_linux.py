# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Linux set-up of a new Keysight 82357B (``ola.gpib_linux``) against a simulated system."""

import json
import os
import re
import shutil
import subprocess

import pytest

from ola import gpib_linux as gl
from ola.gpib_adapter import GpibAdapterConfig, GpibError

UBUNTU = 'NAME="Ubuntu"\nID=ubuntu\nID_LIKE=debian\nPRETTY_NAME="Ubuntu 24.04.1 LTS"\n'
LANG_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend", "lang", "modules", "gpib")


class FakeProbe(gl.SystemProbe):
    """A Linux system described by sets and dictionaries."""

    platform = "linux"

    def __init__(self, **kw):
        self.files = {"/etc/os-release": UBUNTU}
        self.files.update(kw.pop("files", {}))
        self.paths = set(kw.pop("paths", ()))
        self.commands = dict(kw.pop("commands", {}))  # name -> path
        self.results = dict(kw.pop("results", {}))  # "modinfo" -> (rc, out)
        self.usb = kw.pop("usb", [(0x0957, 0x0518)])
        self.kernel = kw.pop("kernel", "6.8.0-45-generic")
        self.members = kw.pop("members", None)
        self.session = kw.pop("session", [])
        self.modules = set(kw.pop("modules", ()))
        self.rw = kw.pop("rw", True)
        assert not kw, kw

    def read_text(self, path):
        return self.files.get(path)

    def exists(self, path):
        return path in self.paths or path in self.files

    def access_rw(self, path):
        return self.rw

    def which(self, command):
        return self.commands.get(command)

    def run(self, argv, timeout=10):
        return self.results.get(argv[0], (127, "not found"))

    def glob(self, pattern):
        rx = re.compile("^" + re.escape(pattern).replace(r"\*", ".*") + "$")
        return sorted(p for p in self.paths if rx.match(p))

    def usb_devices(self):
        return self.usb

    def kernel_release(self):
        return self.kernel

    def user(self):
        return "erik"

    def group_members(self, group):
        return self.members

    def session_groups(self):
        return self.session

    def find_spec(self, module):
        return module in self.modules


def ready_probe(**kw):
    """A system where everything is done."""
    values = dict(
        files={
            "/etc/os-release": UBUNTU,
            "/etc/gpib.conf": gl.interface_block(0, "agilent_82357a"),
        },
        paths={
            "/usr/local/lib/libgpib.so.0",
            "/usr/share/usb/agilent_82357a/measat_releaseX1.8.hex",
            "/etc/udev/rules.d/99-agilent_82357a.rules",
            "/sys/module/agilent_82357a",
            "/dev/gpib0",
        },
        commands={
            "gpib_config": "/usr/local/sbin/gpib_config",
            "fxload": "/usr/sbin/fxload",
            "gcc": "/usr/bin/gcc",
            "make": "/usr/bin/make",
        },
        results={
            "modinfo": (0, "filename: agilent_82357a.ko"),
            "mokutil": (0, "SecureBoot disabled"),
        },
        usb=[(0x0957, 0x0718)],
        members=["erik"],
        session=["erik", "gpib"],
        modules={"gpib_ctypes"},
    )
    values.update(kw)
    return FakeProbe(**values)


CFG = GpibAdapterConfig()  # Keysight 82357B on GPIB0


def status(report):
    return {s.id: s.status for s in report.steps}


# ----- check -------------------------------------------------------------------------------------
def test_new_adapter_on_a_new_ubuntu():
    report = gl.check_linux_setup(CFG, FakeProbe(results={"mokutil": (0, "SecureBoot disabled")}))
    st = status(report)
    assert report.manager == "apt"
    for step in (
        "build_tools",
        "linux_gpib_user",
        "kernel_module",
        "fxload",
        "firmware",
        "udev_rule",
        "gpib_conf",
        "gpib_group",
        "python_bindings",
    ):
        assert st[step] == gl.MISSING, step
    assert st["usb_state"] == gl.WARN  # 0957:0518: no firmware yet
    assert st["dev_node"] == gl.WARN
    assert st["secure_boot"] == gl.OK
    assert report.root_fixes == ["packages", "linux_gpib", "firmware", "udev", "gpib_conf", "group"]
    assert report.needs_python
    fw = report.step("firmware")
    assert fw.values["file"] == "measat_releaseX1.8.hex"
    for step in report.steps:
        assert step.text  # every message formats with its values


def test_everything_done():
    report = gl.check_linux_setup(CFG, ready_probe())
    assert set(status(report).values()) <= {gl.OK, gl.INFO}
    assert report.root_fixes == [] and not report.needs_python
    assert gl.build_setup_script(report) == ""


def test_group_added_but_not_yet_in_the_session():
    report = gl.check_linux_setup(CFG, ready_probe(session=["erik"]))
    assert report.step("gpib_group").status == gl.WARN
    assert report.root_fixes == []


def test_secure_boot_on_blocks_a_module_built_here():
    probe = ready_probe(results={"modinfo": (1, ""), "mokutil": (0, "SecureBoot enabled")})
    report = gl.check_linux_setup(CFG, probe)
    assert report.step("secure_boot").status == gl.WARN
    assert "GPIB-009" in report.step("secure_boot").text


def test_kernel_with_in_tree_drivers():
    probe = ready_probe(results={"modinfo": (1, "")}, kernel="6.14.2-arch1-1")
    report = gl.check_linux_setup(CFG, probe)
    assert report.step("kernel_module").key == "lx_module_missing_intree"
    assert report.root_fixes == []  # nothing the script can build


def test_board_number_and_gpib_conf_with_another_board():
    conf = gl.interface_block(0, "ni_pci")
    probe = ready_probe(files={"/etc/os-release": UBUNTU, "/etc/gpib.conf": conf})
    report = gl.check_linux_setup(GpibAdapterConfig(board=1), probe)
    assert report.step("gpib_conf").status == gl.MISSING
    assert report.step("dev_node").values["device"] == "/dev/gpib1"


@pytest.mark.parametrize(
    "release, manager",
    [
        ("ID=fedora\n", "dnf"),
        ("ID=arch\n", "pacman"),
        ('ID="opensuse-tumbleweed"\nID_LIKE="opensuse suse"\n', "zypper"),
        ("ID=linuxmint\nID_LIKE=ubuntu\n", "apt"),
        ("ID=gentoo\n", None),
    ],
)
def test_distributions(release, manager):
    probe = FakeProbe(files={"/etc/os-release": release})
    report = gl.check_linux_setup(CFG, probe)
    assert report.manager == manager
    script = gl.build_setup_script(report)
    if manager:
        assert gl.PACKAGE_MANAGERS[manager]["install"] in script
    else:
        assert report.step("distro").status == gl.WARN
        assert "unknown distribution" in script


def test_ni_adapter_has_no_firmware_steps():
    report = gl.check_linux_setup(GpibAdapterConfig(profile="ni_gpib_usb_hs"), FakeProbe())
    ids = {s.id for s in report.steps}
    assert not ids & {"fxload", "firmware", "udev_rule", "usb_state"}
    assert "ni_usb_b" in gl.build_setup_script(report)


def test_linux_setup_only_on_linux_for_linux_gpib_adapters():
    assert gl.supports_linux_setup(CFG, "linux")
    assert not gl.supports_linux_setup(CFG, "win32")
    assert not gl.supports_linux_setup(GpibAdapterConfig(profile="prologix_usb", port="x"), "linux")


def test_pyvisa_board_check():
    from tests.test_gpib_adapter import FakeBus, FakeRM

    bus = FakeBus({})
    report = gl.check_linux_setup(CFG, ready_probe(), rm_factory=lambda b="": FakeRM(bus))
    assert report.step("pyvisa_board").status == gl.OK
    report = gl.check_linux_setup(
        GpibAdapterConfig(board=3), ready_probe(), rm_factory=lambda b="": FakeRM(bus)
    )
    assert report.step("pyvisa_board").status == gl.WARN


# ----- gpib.conf ----------------------------------------------------------------------------------
def test_gpib_conf_new_file():
    text = gl.gpib_conf_text("", 0, "agilent_82357a")
    assert gl.find_interface(text, 0) == {"board_type": "agilent_82357a", "name": "gpib0"}
    assert "master = yes" in text


def test_gpib_conf_keeps_the_other_boards_and_devices():
    template = (
        "/* comment with interface { minor = 0 } inside */\n"
        + gl.interface_block(0, "ni_pci")
        + gl.interface_block(1, "ni_usb_b")
        + 'device {\n\tminor = 0\n\tname = "dmm"\n\tpad = 7\n}\n'
    )
    text = gl.gpib_conf_text(template, 0, "agilent_82357a")
    assert gl.find_interface(text, 0)["board_type"] == "agilent_82357a"
    assert gl.find_interface(text, 1)["board_type"] == "ni_usb_b"
    assert 'name = "dmm"' in text
    assert text.count("interface {") == 3  # two blocks and the commented one
    again = gl.gpib_conf_text(text, 0, "agilent_82357a")
    assert again == text  # running it again changes nothing


def test_gpib_conf_adds_a_new_minor():
    text = gl.gpib_conf_text(gl.interface_block(0, "ni_pci"), 2, "agilent_82357a")
    assert gl.find_interface(text, 0)["board_type"] == "ni_pci"
    assert gl.find_interface(text, 2)["board_type"] == "agilent_82357a"


# ----- udev and script ---------------------------------------------------------------------------
def test_udev_rule_for_the_82357b():
    rule = gl.udev_rule_text("keysight_82357b", 0)
    assert 'ATTR{idProduct}=="0518"' in rule and "-t fx2" in rule
    assert "measat_releaseX1.8.hex" in rule
    assert 'ATTR{idProduct}=="0718"' in rule and "--minor 0" in rule
    assert 'GROUP="gpib"' in rule
    rule_a = gl.udev_rule_text("keysight_82357a", 1)
    assert 'ATTR{idProduct}=="0007"' in rule_a and "-t fx " in rule_a and "82357a_fw.hex" in rule_a


def test_script_for_a_new_adapter():
    report = gl.check_linux_setup(CFG, FakeProbe())
    script = gl.build_setup_script(report, firmware_dir="/home/erik/fw")
    assert script.startswith("#!/bin/bash")
    assert "set -euo pipefail" in script
    assert "apt-get install -y" in script and "fxload" in script and "build-essential" in script
    assert "pkg_available linux-gpib" in script  # distribution package first...
    assert gl.LINUX_GPIB_URL in script  # ...then the release tarball
    assert "./configure --sysconfdir=/etc" in script and "ldconfig" in script
    assert 'ver_lt "${KREL%%-*}" "6.13"' in script
    assert "FIRMWARE_SRC=/home/erik/fw" in script and gl.FIRMWARE_URL in script
    assert "measat_releaseX1.8.hex" in script
    assert gl.OUR_UDEV_RULE in script
    assert 'board_type = "agilent_82357a"' in script and "ola-backup" in script
    assert 'usermod -aG gpib "$TARGET_USER"' in script and "TARGET_USER=erik" in script
    assert 'modprobe "$DRIVER"' in script


def test_script_only_for_what_is_missing():
    probe = ready_probe(members=None, session=["erik"])
    report = gl.check_linux_setup(CFG, probe)
    assert report.root_fixes == ["group"]
    script = gl.build_setup_script(report)
    assert "groupadd -f gpib" in script
    assert "Packages:" not in script and "linux-gpib $LINUX_GPIB_VERSION" not in script
    assert "/etc/gpib.conf:" not in script and "Firmware" not in script


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
@pytest.mark.parametrize("release", [UBUNTU, "ID=fedora\n", "ID=gentoo\n"])
def test_script_is_valid_bash(tmp_path, release):
    report = gl.check_linux_setup(CFG, FakeProbe(files={"/etc/os-release": release}))
    path = tmp_path / "setup.sh"
    path.write_text(gl.build_setup_script(report))
    done = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


# ----- running -----------------------------------------------------------------------------------
def test_run_setup_with_pkexec(tmp_path):
    calls, lines = [], []

    def runner(argv, on_output):
        calls.append(list(argv))
        with open(argv[-1]) as f:
            assert f.read() == "#!/bin/bash\necho hi\n"
        on_output("==> step")
        return 0

    rc = gl.run_setup(
        "#!/bin/bash\necho hi\n",
        lines.append,
        runner,
        which=lambda c: "/usr/bin/pkexec",
        folder=str(tmp_path),
    )
    assert rc == 0 and lines == ["==> step"]
    assert calls[0][:2] == ["/usr/bin/pkexec", "/bin/bash"]
    assert not os.path.exists(calls[0][2])  # the script is removed afterwards


def test_run_setup_failure(tmp_path):
    with pytest.raises(GpibError) as exc:
        gl.run_setup(
            "x", runner=lambda argv, out: 3, which=lambda c: "/usr/bin/pkexec", folder=str(tmp_path)
        )
    assert exc.value.code == "GPIB-008" and "3" in str(exc.value)


def test_run_setup_without_pkexec(tmp_path):
    with pytest.raises(GpibError) as exc:
        gl.run_setup("x", which=lambda c: None, folder=str(tmp_path))
    assert exc.value.code == "GPIB-008" and "sudo bash" in str(exc.value)
    path = str(exc.value).split("sudo bash ")[1]
    assert os.path.exists(path) and oct(os.stat(path).st_mode)[-3:] == "700"


def test_install_python_bindings():
    seen = []
    assert gl.install_python_bindings(runner=lambda argv, out: seen.append(argv) or 0) == 0
    assert seen[0][1:] == ["-m", "pip", "install", "gpib-ctypes"]
    with pytest.raises(GpibError):
        gl.install_python_bindings(runner=lambda argv, out: 1)


def test_kernel_version():
    assert gl.kernel_version("6.8.0-45-generic") == (6, 8)
    assert gl.kernel_version("6.13.1-arch1") == (6, 13)
    assert gl.kernel_version("") == (0, 0)


# ----- translations ------------------------------------------------------------------------------
@pytest.mark.parametrize("lang", ["it", "en", "fr", "es", "de"])
def test_every_message_is_translated(lang):
    with open(os.path.join(LANG_DIR, f"{lang}.json"), encoding="utf-8") as f:
        catalog = json.load(f)
    assert [k for k in gl.MESSAGES if k not in catalog] == []
    placeholder = re.compile(r"\{(\w+)\}")
    for key, text in gl.MESSAGES.items():
        assert set(placeholder.findall(catalog[key])) == set(placeholder.findall(text)), key
