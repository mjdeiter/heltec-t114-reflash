#!/usr/bin/env python3
"""
heltec_reflash.py — Remotely trigger the Adafruit-style nRF52 bootloader on the
Heltec Mesh Node T114 (Meshtastic) via a 1200bps USB-CDC "touch" reset, then
copy a UF2 firmware image onto the bootloader's mass-storage drive.

This replaces the physical double-tap-reset-button step so the reflash can be
done over a remote shell.

Usage:
    sudo python3 heltec_reflash.py /path/to/firmware.uf2
"""

import sys
import os
import time
import glob
import subprocess

try:
    import serial
except ImportError:
    print("[-] pyserial not found. Install with: pip install pyserial (or pacman -S python-pyserial)")
    sys.exit(1)

VID = "239a"       # Adafruit/Heltec nRF52 vendor ID
PID_APP = "4405"   # application (CDC ACM) mode
PID_BOOT = "0071"  # bootloader (mass storage) mode
MOUNT_POINT = "/tmp/ht-reflash"


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


def flash(blockdev, fw_path):
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


def main():
    if len(sys.argv) != 2:
        print("Usage: sudo python3 heltec_reflash.py <firmware.uf2>")
        sys.exit(1)

    fw_path = sys.argv[1]
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
        wait_until(lambda: not os.path.exists(app_dev), timeout=10, label="serial port disconnect")
    else:
        print("[!] No device in application mode found on /dev/ttyACM*.")
        print("    Assuming it may already be sitting in bootloader mode.")

    print("[*] Waiting for bootloader mass-storage device to appear...")
    blockdev = wait_until(find_boot_blockdev, timeout=15, label="bootloader mass-storage device")
    if not blockdev:
        print("[-] Could not find the device in bootloader mode. Aborting.")
        print("    It may still be crash-looping in app mode — try running this again.")
        sys.exit(1)

    print(f"[+] Bootloader device found: {blockdev}")
    flash(blockdev, fw_path)

    print("[*] Waiting for device to re-enumerate in application mode (up to 30s)...")
    result = wait_until(find_app_tty, timeout=30, interval=1, label="application mode re-enumeration")

    if result:
        print(f"[SUCCESS] Device is back up cleanly as {result}")
    else:
        print("[WARN] Device did not come back within 30s.")
        print("        Check `dmesg` / `journalctl -k` manually — it may still be looping,")
        print("        or it may just need a few more seconds.")


if __name__ == "__main__":
    main()
