#!/usr/bin/env python3
"""
heltec_reflash.py — Remotely re-flash a Heltec Mesh Node T114 (Meshtastic,
nRF52-based) over USB, without needing physical access to the reset button.

Primary path:
    1. Find the device in application mode on /dev/ttyACM* (VID 239a, PID 4405).
    2. Perform a 1200bps USB-CDC "touch" to request a bootloader reset.
    3. Wait for it to re-enumerate as a UF2 mass-storage volume (PID 0071
       with a block device present).
    4. Mount it, copy the given .uf2 file, sync, and let it flash/self-reset.
    5. Confirm it comes back up cleanly in application mode.

Fallback path (automatic):
    Sometimes the 1200bps touch lands the bootloader in *serial DFU* mode
    instead — same PID (0071), same ttyACM device, but no mass-storage
    interface ever appears. In that case this script:
    1. Converts the given .uf2 to a raw application binary (uf2_to_bin.py).
    2. Packages it as a Nordic DFU .zip via `adafruit-nrfutil dfu genpkg`
       (wildcard device-type/softdevice fields — app-only update, no
       bootloader/softdevice changes).
    3. Pushes it with `adafruit-nrfutil dfu serial`.
    4. Re-checks for the mass-storage volume regardless of that command's
       reported result — in testing, the DFU *init packet* alone was enough
       to trigger a reset that revealed the mass-storage volume, even when
       the bulk transfer that followed it errored out. When that happens,
       this script finishes the job through the normal, more reliable UF2
       copy rather than trusting the serial transfer to have completed.

Requires: pyserial (required), adafruit-nrfutil (optional, only needed if
the fallback path is used).

Usage:
    sudo python3 heltec_reflash.py /path/to/firmware.uf2
    sudo python3 heltec_reflash.py /path/to/firmware.uf2 --no-fallback
    sudo python3 heltec_reflash.py /path/to/firmware.uf2 --msc-timeout 90
"""

import argparse
import os
import shutil
import subprocess
import sys
import time
import glob

try:
    import serial
except ImportError:
    print("[-] pyserial not found. Install with: pip install pyserial (or pacman -S python-pyserial)")
    sys.exit(1)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from uf2_to_bin import convert as uf2_to_bin

VID = "239a"       # Adafruit/Heltec nRF52 vendor ID
PID_APP = "4405"   # application (CDC ACM) mode
PID_BOOT = "0071"  # bootloader mode (mass storage, or serial-DFU-only)
MOUNT_POINT = "/tmp/ht-reflash"
WORK_DIR = "/tmp/ht-reflash-work"


def udev_props(devnode):
    out = subprocess.run(
        ["udevadm", "info", "-q", "property", "-n", devnode],
        capture_output=True, text=True
    ).stdout
    return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)


def find_app_tty():
    for dev in sorted(glob.glob("/dev/ttyACM*")):
        props = udev_props(dev)
        if props.get("ID_VENDOR_ID") == VID and props.get("ID_MODEL_ID") == PID_APP:
            return dev
    return None


def find_boot_tty():
    for dev in sorted(glob.glob("/dev/ttyACM*")):
        props = udev_props(dev)
        if props.get("ID_VENDOR_ID") == VID and props.get("ID_MODEL_ID") == PID_BOOT:
            return dev
    return None


def find_boot_blockdev():
    for sd in sorted(glob.glob("/sys/block/sd*")):
        name = os.path.basename(sd)
        devnode = f"/dev/{name}"
        props = udev_props(devnode)
        if props.get("ID_VENDOR_ID") == VID and props.get("ID_MODEL_ID") == PID_BOOT:
            part = f"{devnode}1"
            return part if os.path.exists(part) else devnode
    return None


def touch_1200bps(dev):
    print(f"[*] Touching {dev} at 1200 baud to request bootloader reset...")
    ser = serial.Serial(dev, 1200)
    try:
        ser.dtr = False
    except Exception:
        pass
    time.sleep(0.25)
    ser.close()


def wait_until(predicate, timeout, interval=0.5, label=""):
    t0 = time.time()
    while time.time() - t0 < timeout:
        result = predicate()
        if result:
            return result
        time.sleep(interval)
    print(f"[-] Timed out waiting for: {label}")
    return None


def flash_uf2(blockdev, fw_path):
    os.makedirs(MOUNT_POINT, exist_ok=True)
    print(f"[*] Mounting {blockdev} -> {MOUNT_POINT}")
    subprocess.run(["mount", blockdev, MOUNT_POINT], check=True)

    dest = os.path.join(MOUNT_POINT, os.path.basename(fw_path))
    print(f"[*] Copying firmware -> {dest}")
    subprocess.run(["cp", fw_path, dest], check=True)
    subprocess.run(["sync"], check=False)
    print("[+] Copy issued. The bootloader will flash and self-reset once it")
    print("    sees the final block — it's normal for the drive to vanish")
    print("    abruptly and for the OS to log a harmless I/O error after that.")


def dfu_fallback(boot_dev, fw_path, msc_timeout):
    """Attempt Nordic serial DFU. Regardless of that command's own reported
    result, re-check for the mass-storage volume and finish through the
    standard UF2 copy path if it appears — see module docstring."""
    nrfutil = shutil.which("adafruit-nrfutil")
    if not nrfutil:
        print("[-] No mass-storage volume appeared, and adafruit-nrfutil is not")
        print("    installed, so the serial DFU fallback can't run.")
        print("    Install with: pip install adafruit-nrfutil")
        return False

    os.makedirs(WORK_DIR, exist_ok=True)
    bin_path = os.path.join(WORK_DIR, "app.bin")
    pkg_path = os.path.join(WORK_DIR, "dfu-pkg.zip")

    print("[*] No mass-storage volume yet — device may be in serial-DFU-only")
    print("    mode. Building a DFU package as a fallback...")
    uf2_to_bin(fw_path, bin_path)

    genpkg_cmd = [nrfutil, "dfu", "genpkg", "--application", bin_path,
                  "--dfu-ver", "0.5", pkg_path]
    print(f"[*] Packaging: {' '.join(genpkg_cmd)}")
    result = subprocess.run(genpkg_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("[-] genpkg failed:")
        print(result.stdout)
        print(result.stderr)
        return False

    serial_cmd = [nrfutil, "dfu", "serial", "-pkg", pkg_path,
                  "-p", boot_dev, "-b", "115200", "--singlebank"]
    print(f"[*] Pushing over serial (best-effort): {' '.join(serial_cmd)}")
    dfu_result = subprocess.run(serial_cmd, capture_output=True, text=True)
    print(dfu_result.stdout)
    if dfu_result.returncode != 0:
        print("[!] Serial DFU push reported an error (this can be expected —")
        print("    checking whether it nudged the bootloader into mass-storage")
        print("    mode anyway)...")
        print(dfu_result.stderr)

    blockdev = wait_until(find_boot_blockdev, timeout=msc_timeout,
                           label="mass-storage volume after DFU attempt")
    if blockdev:
        print(f"[+] Mass-storage volume appeared: {blockdev}")
        flash_uf2(blockdev, fw_path)
        return True

    if dfu_result.returncode == 0:
        print("[+] Serial DFU reported success and no mass-storage volume was")
        print("    needed.")
        return True

    print("[-] Serial DFU failed and no mass-storage volume appeared.")
    print("    The device may still be recoverable — try running this script")
    print("    again, or fall back to a physical double-press if possible.")
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("firmware", help="Path to the .uf2 firmware file")
    parser.add_argument("--msc-timeout", type=int, default=60,
                         help="Seconds to wait for the mass-storage volume to "
                              "appear after a bootloader reset (default: 60 — "
                              "this has been observed to take up to ~90s)")
    parser.add_argument("--no-fallback", action="store_true",
                         help="Don't attempt the serial DFU fallback if mass "
                              "storage never appears")
    args = parser.parse_args()

    fw_path = args.firmware
    if not os.path.isfile(fw_path):
        print(f"[-] Firmware file not found: {fw_path}")
        sys.exit(1)

    if os.geteuid() != 0:
        print("[-] This script needs root (for mount). Re-run with sudo.")
        sys.exit(1)

    app_dev = find_app_tty()

    if app_dev:
        print(f"[+] Found device in application mode: {app_dev}")
        touch_1200bps(app_dev)
        print("[*] Waiting for device to drop off as a serial port...")
        wait_until(lambda: not os.path.exists(app_dev), timeout=10,
                   label="serial port disconnect")
    else:
        print("[!] No device in application mode found on /dev/ttyACM*.")
        print("    Assuming it may already be sitting in bootloader mode.")

    print("[*] Waiting for bootloader mass-storage device to appear "
          f"(up to {args.msc_timeout}s)...")
    blockdev = wait_until(find_boot_blockdev, timeout=args.msc_timeout,
                           label="bootloader mass-storage device")

    if not blockdev:
        boot_dev = find_boot_tty()
        if not boot_dev:
            print("[-] Device isn't reachable in either mode. Aborting.")
            print("    It may still be crash-looping in app mode — try running this again.")
            sys.exit(1)

        if args.no_fallback:
            print(f"[-] Found bootloader serial port ({boot_dev}) but no mass "
                  "storage, and --no-fallback was set. Aborting.")
            sys.exit(1)

        ok = dfu_fallback(boot_dev, fw_path, args.msc_timeout)
        if not ok:
            sys.exit(1)
    else:
        print(f"[+] Bootloader device found: {blockdev}")
        flash_uf2(blockdev, fw_path)

    print("[*] Waiting for device to re-enumerate in application mode (up to 30s)...")
    result = wait_until(find_app_tty, timeout=30, interval=1,
                         label="application mode re-enumeration")

    if result:
        print(f"[SUCCESS] Device is back up cleanly as {result}")
    else:
        print("[WARN] Device did not come back within 30s.")
        print("        Check `dmesg` / `journalctl -k` manually — it may still be looping,")
        print("        or it may just need a few more seconds.")


if __name__ == "__main__":
    main()
