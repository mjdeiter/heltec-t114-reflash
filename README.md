# heltec-t114-reflash

Remotely re-flash a Heltec Mesh Node T114 (Meshtastic, nRF52-based) over USB
without needing physical access to the reset button.

## Why

The T114's Adafruit-style nRF52 bootloader normally requires a physical
double-press of the reset button to drop into UF2 mass-storage mode for
drag-and-drop flashing. That's not possible when the device is headless or
remote. This script uses the standard **1200bps USB-CDC "touch" trick** (open
the serial port at 1200 baud, drop DTR, close) to request the same bootloader
reset entirely over software.

## What it does

1. Finds the device in application mode on `/dev/ttyACM*` (VID `239a`, PID `4405`).
2. Performs the 1200bps touch to trigger a bootloader reset.
3. Waits for the device to re-enumerate as a UF2 mass-storage volume
   (VID `239a`, PID `0071` with a block device present).
4. Mounts it, copies the given `.uf2` firmware file, and syncs.
5. Waits for the device to come back up cleanly in application mode.

### Automatic DFU fallback

In practice, the 1200bps touch doesn't always land the bootloader in
mass-storage mode. Sometimes it comes up as the *same* PID (`0071`) but with
only a serial (CDC-ACM) interface — no mass storage ever appears. This is a
distinct bootloader personality meant for Nordic's serial DFU protocol, not
drag-and-drop UF2, and it needs a signed `.zip` package instead of a raw
`.uf2` file.

When this happens, the script now falls back automatically:

1. Converts the `.uf2` to a raw application binary (`uf2_to_bin.py`).
2. Packages it as an app-only Nordic DFU `.zip` via `adafruit-nrfutil dfu
   genpkg` (wildcard device-type/softdevice fields, so it doesn't need exact
   hardware metadata — the bootloader will simply reject it cleanly if
   something's incompatible, rather than corrupt anything).
3. Pushes it with `adafruit-nrfutil dfu serial`.
4. **Re-checks for the mass-storage volume regardless of that command's own
   result.** In testing, sending the DFU *init packet* alone was enough to
   trigger a reset that revealed the mass-storage volume, even when the bulk
   transfer that followed it errored out. When that happens, the script
   finishes the job through the normal, more reliable UF2 copy rather than
   trusting the serial transfer to have completed on its own.

This fallback needs `adafruit-nrfutil` installed. If it isn't, and mass
storage never appears, the script exits with instructions rather than
guessing.

## Requirements

- `pyserial` (required)
- `adafruit-nrfutil` (optional — only used by the DFU fallback path)

## Usage

```
pip install pyserial adafruit-nrfutil
sudo python3 heltec_reflash.py /path/to/firmware.uf2
```

Must be run as root (needed to mount the bootloader's mass-storage volume).

Options:

```
--msc-timeout SECONDS   How long to wait for the mass-storage volume to
                         appear after a bootloader reset (default: 60).
                         This has been observed to take up to ~90s in
                         practice — the reset isn't always fast.
--no-fallback            Don't attempt the serial DFU fallback if mass
                         storage never appears; just fail with instructions.
```

## Notes / gotchas

- **Timing is inconsistent.** The gap between the 1200bps touch and the
  device actually re-enumerating in bootloader mode has been observed
  anywhere from a few seconds to ~90 seconds. The default `--msc-timeout` of
  60s covers most cases, but bump it if you see a timeout on a device that's
  otherwise healthy.
- A single `cp` + `sync` for the UF2 copy is intentional — the nRF52 UF2
  bootloader's fake FAT filesystem is picky about write patterns and can
  corrupt if the transfer is interrupted or touched again before it
  self-ejects. **Don't retry a `cp` into the mount if the first one seems
  slow — let it finish.**
- It's normal and harmless for the OS to log an I/O error / "lost async page
  write" when the bootloader vanishes abruptly to flash and reboot. This is
  not a sign of failure by itself.
- **Red herring:** after a successful flash, you may see the kernel log a
  `usb ... reset` for the device roughly every ~100 seconds, which looks
  exactly like a firmware crash loop. In one real case this turned out to be
  unrelated USB autosuspend on the host (`power/control` was `auto` on the
  device's port), not the device itself resetting — the real fix looked like
  it hadn't taken, when it actually had. A genuine firmware crash loop shows
  a full `USB disconnect` + re-enumeration each cycle; a lone `reset` line
  with no disconnect and no new device number is consistent with host-side
  power management instead. If you see this, check:
  ```
  cat /sys/bus/usb/devices/<port>/power/control
  echo on | sudo tee /sys/bus/usb/devices/<port>/power/control
  ```
  Note this override doesn't persist across replug/reboot — use a udev rule
  if you want it permanent.
- If a previous flash attempt was interrupted (e.g. the mass-storage copy
  didn't complete), the device may crash-loop in application mode. Running
  this script again should recover it, since the touch/reset doesn't depend
  on the application firmware being healthy.

## Files

- `heltec_reflash.py` — main script
- `uf2_to_bin.py` — standalone UF2 → raw binary converter, also used
  internally by the DFU fallback path
