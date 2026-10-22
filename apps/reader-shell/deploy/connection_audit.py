#!/usr/bin/env python3
"""Read-only connection audit. No boot, radio initialization or staging fallback.

USB IDs describe candidates, not authenticated board identity. RAM identity is
the existing diagnostic serial/profile contract, not cryptographic attestation.
No saved panel/JSON snapshot is accepted as live evidence. No device data is
written and default CLI output is stdout only.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import stage_ram as stage

SERIAL = 'PANDANOTE966U2_RAM_RO'
RAM_IDS = (0x18d1, 0xd002)
BOOT_IDS = (0xa108, 0xeaef)
MTP_IDS = (0x1d6b, 0x0100)  # retained normal-boot-usb-20261020.json; no serial
MAX_SNAPSHOT_AGE = 2.0


@dataclass(frozen=True, order=True)
class UsbDevice:
    vendor: int
    product: int
    serial: str
    location: int


@dataclass(frozen=True)
class UsbSnapshot:
    devices: tuple
    observed_at: float


@dataclass(frozen=True)
class DeviceState:
    mode: str
    status: str
    identity: str = 'unverified'
    runtime_verified: bool = False
    network_verified: bool = False
    persistently_installed: bool = False
    adb_port: int | None = None
    runtime_profile: str | None = None
    protection: dict = field(default_factory=dict)
    issues: tuple = ()


def parse_ioreg(raw):
    """Parse ioreg's actual plist tree; missing identity is never synthesized."""
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError('USB inventory too large')
    try:
        roots = plistlib.loads(raw)
    except Exception as error:
        raise ValueError('Malformed USB plist') from error
    if not isinstance(roots, list):
        raise ValueError('USB inventory must be a plist array')
    result = []

    def visit(node):
        if not isinstance(node, dict):
            raise ValueError('Malformed USB tree node')
        if 'idVendor' in node or 'idProduct' in node:
            vendor, product = node.get('idVendor'), node.get('idProduct')
            serial, location = node.get('USB Serial Number', ''), node.get('locationID', 0)
            if (type(vendor) is not int or type(product) is not int or
                    not 0 <= vendor <= 65535 or not 0 <= product <= 65535 or
                    not isinstance(serial, str) or len(serial) > 256 or
                    any(ord(c) < 32 for c in serial) or type(location) is not int or location < 0):
                raise ValueError('Malformed USB identity')
            result.append(UsbDevice(vendor, product, serial, location))
        children = node.get('IORegistryEntryChildren', [])
        if not isinstance(children, list):
            raise ValueError('Malformed USB children')
        for child in children:
            visit(child)

    try:
        for node in roots:
            visit(node)
    except RecursionError as error:
        raise ValueError('USB tree too deep') from error
    return tuple(sorted(result))


def collect_usb():
    result = subprocess.run(['/usr/sbin/ioreg', '-a', '-r', '-c', 'IOUSBHostDevice'],
                            capture_output=True, timeout=5)
    if result.returncode:
        raise RuntimeError('USB inventory inaccessible')
    return UsbSnapshot(parse_ioreg(result.stdout), time.monotonic())


def fresh_snapshot():
    snapshot = collect_usb()
    age = time.monotonic() - snapshot.observed_at
    if not 0 <= age <= MAX_SNAPSHOT_AGE:
        raise ValueError('Stale or future USB inventory')
    return snapshot


def classify(devices):
    ram = [d for d in devices if (d.vendor, d.product) == RAM_IDS or d.serial == SERIAL]
    boot = [d for d in devices if (d.vendor, d.product) == BOOT_IDS]
    mtp = [d for d in devices if (d.vendor, d.product) == MTP_IDS]
    if ram:
        if (len(ram) != 1 or boot or mtp or ram[0].serial != SERIAL or
                (ram[0].vendor, ram[0].product) != RAM_IDS):
            raise ValueError('Unknown, duplicate or mixed reader identity/mode')
        return 'ram'
    if boot:
        if len(boot) != 1 or mtp:
            raise ValueError('Duplicate or mixed boot candidates')
        return 'bootrom_candidate'
    if mtp:
        if len(mtp) != 1:
            raise ValueError('Duplicate normal-mode candidates')
        return 'normal_mtp_unverified'
    return 'unverified_usb' if devices else 'inaccessible'


def require_exact_adb(text):
    lines = text.splitlines()
    if not lines or lines[0] != 'List of devices attached':
        raise ValueError('Malformed ADB enumeration')
    rows = [line.split() for line in lines[1:] if line.strip()]
    if len(rows) != 1 or rows[0][:2] != [SERIAL, 'device']:
        raise ValueError('Missing, foreign, duplicate or unavailable ADB target')
    if any(not re.fullmatch(r'[A-Za-z_]+:[^\s]+', token) for token in rows[0][2:]):
        raise ValueError('Malformed ADB transport metadata')


class ReadOnlyAdb:
    """Allowlist over ExistingAdb; every query rechecks USB and all ADB targets.

    ExistingAdb explicitly uses -H127.0.0.1, so an absent server fails rather
    than invoking adb's local-server startup path. Never tries other ports.
    """
    def __init__(self, port, snapshot):
        self.transport = stage.ExistingAdb(port)
        self.snapshot = snapshot
        self.deadline = time.monotonic() + 90
        self.allowed = set(stage.preflight.COMMANDS.values()) | set(stage.PROFILE_COMMANDS.values())

    def recheck(self):
        if time.monotonic() >= self.deadline:
            raise ValueError('Connection audit deadline exceeded')
        current = fresh_snapshot()
        if current.devices != self.snapshot.devices or classify(current.devices) != 'ram':
            raise ValueError('USB identity/mode changed during audit')
        result = self.transport.run(['devices', '-l'], timeout=10)
        if result.returncode:
            raise RuntimeError('Existing ADB server unavailable')
        require_exact_adb(result.stdout)
        if fresh_snapshot().devices != self.snapshot.devices:
            raise ValueError('USB identity/mode changed during ADB enumeration')

    def run(self, args):
        if args not in (['get-serialno'], ['get-state']):
            raise ValueError('Non-diagnostic ADB operation refused')
        self.recheck()
        return self.transport.run(args, timeout=10)

    def shell(self, command):
        if command not in self.allowed:
            raise ValueError('Non-diagnostic shell operation refused')
        self.recheck()
        output = self.transport.shell(command)
        # Legacy validator accepts a missing lo entry; require complete,
        # unique flag evidence for both profiles before delegating protection.
        if command == stage.preflight.COMMANDS['network']:
            seen = set()
            for line in output.splitlines():
                match = re.fullmatch(r'(/sys/class/net/[A-Za-z0-9_.-]+/flags) (0x[0-9a-fA-F]{1,8})', line)
                if not match or match[1] in seen:
                    raise ValueError('Invalid or duplicate interface evidence')
                seen.add(match[1])
            if '/sys/class/net/lo/flags' not in seen:
                raise ValueError('Missing loopback interface evidence')
        return output


def audit_connection(*, adb_port=None, profile=stage.LEGACY_PROFILE, opt_libraries=False) -> DeviceState:
    """Collect current read-only evidence. Never starts services or boots a reader."""
    mode = 'inaccessible'
    try:
        if adb_port not in (None, 5037, 5039):
            raise ValueError('Unsupported existing local ADB port')
        if profile not in (stage.LEGACY_PROFILE, stage.NETWORK_PROFILE):
            raise ValueError('Unknown runtime profile')
        if opt_libraries and profile != stage.NETWORK_PROFILE:
            raise ValueError('Optional library mount requires explicit reviewed network profile')
        snapshot = fresh_snapshot()
        mode = classify(snapshot.devices)
        if mode != 'ram':
            issue = ('USB descriptors alone do not confirm 966U2 identity; no CPU_INFO provider is used.'
                     if mode == 'bootrom_candidate' else
                     'Normal MTP identity/serial is unverified; no normal-system device commands are supported.')
            return DeviceState(mode, 'unverified_or_inaccessible', issues=(issue,))
        if adb_port is None:
            return DeviceState(mode, 'adb_not_selected', issues=('Select the existing local ADB server explicitly.',))
        adb = ReadOnlyAdb(adb_port, snapshot)
        state = adb.run(['get-state'])
        if state.returncode or state.stdout.strip() != 'device':
            raise ValueError('RAM target state unavailable')
        proof = stage.protection(adb, profile, opt_libraries=opt_libraries)
        adb.recheck()
        # No raw /proc tables, USB inventory, private content or server stderr
        # enter the report. Validation is a checkpoint, never action permission.
        return DeviceState(mode, 'readonly_runtime_verified', identity='exact_ram_diagnostic_contract',
                           runtime_verified=True, adb_port=adb_port, runtime_profile=profile,
                           protection={key: proof['validation'][key] for key in ('root', 'disk_ro')})
    except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        issue = str(error) if isinstance(error, ValueError) else 'Read-only observation unavailable, interrupted or incomplete'
        return DeviceState(mode, 'stopped', adb_port=adb_port, issues=(issue,))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb-port', type=int, choices=(5037, 5039),
                        help='Explicit existing loopback ADB server; omitted means USB inventory only')
    parser.add_argument('--runtime-profile', choices=(stage.LEGACY_PROFILE, stage.NETWORK_PROFILE),
                        default=stage.LEGACY_PROFILE)
    parser.add_argument('--opt-libraries', action='store_true')
    args = parser.parse_args(argv)
    state = audit_connection(adb_port=args.adb_port, profile=args.runtime_profile, opt_libraries=args.opt_libraries)
    import json
    print(json.dumps(asdict(state), indent=2))
    return 0 if state.runtime_verified else 2


if __name__ == '__main__':
    raise SystemExit(main())
