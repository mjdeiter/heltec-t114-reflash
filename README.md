# heltec-t114-reflash

Remotely re-flash a Heltec Mesh Node T114 (Meshtastic, nRF52-based) over USB
without needing physical access to the reset button.

## Why

The T114's Adafruit-style nRF52 bootloader normally requires a physical
double-press of the reset button to drop into UF2 mass-storage mode for
drag-and-drop flashing. That's not possible when the device is headless or
remote. This script uses the standard **1200bps USB-CDC "touch" trick**
(open the serial port at 1200 baud, drop DTR, close) to request the same
bootloader reset entirely over software.

## What it does

1. Finds the device in application mode on `/dev/ttyACM*` (VID `239a`, PID `4405`).
2. Performs the 1200bps touch to trigger a bootloader reset.
3. Waits for the device to re-enumerate as a UF2 mass-storage volume
   (VID `239a`, PID `0071`).
4. Mounts it, copies the given `.uf2` firmware file, and syncs.
5. Waits for the device to come back up cleanly in application mode.

## Usage

```bash
pip install pyserial
sudo python3 heltec_reflash.py /path/to/firmware.uf2
```

Must be run as root (needed to mount the bootloader's mass-storage volume).

## Notes / gotchas

- The 1200bps touch only reaches the bootloader's **mass-storage** UF2 mode
  on this board when it drops cleanly from application mode. If the device
  is already crash-looping (e.g. from a previously interrupted flash), the
  serial touch may instead land it in **serial DFU mode** (CDC-only, no mass
  storage) — that needs a signed DFU `.zip` package and `nrfutil` instead of
  a raw `.uf2`, which this script does not handle.
- A single `cp` + `sync` is intentional — the nRF52 UF2 bootloader's fake FAT
  filesystem is picky about write patterns and can corrupt if the transfer
  is interrupted or touched again before it self-ejects.
- It's normal and harmless for the OS to log an I/O error / "lost async page
  write" when the bootloader vanishes abruptly to flash and reboot.
