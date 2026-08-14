# Changelog

All notable changes to this project are documented here.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.1.0] - 2026-08-13

### Added
- Automatic serial-DFU fallback in `heltec_reflash.py` for when the 1200bps
  touch lands the bootloader in serial-only mode (no mass storage). Builds
  an app-only Nordic DFU package on the fly and pushes it via
  `adafruit-nrfutil`, then re-checks for the mass-storage volume and
  finishes through the standard UF2 copy if it appears.
- `uf2_to_bin.py` — standalone UF2 → raw binary converter, used by the new
  fallback path and usable on its own.
- `--msc-timeout` CLI option (default 60s, up from a hardcoded 15s) to
  accommodate observed real-world delays of up to ~90s between the touch and
  the bootloader fully re-enumerating.
- `--no-fallback` CLI option to disable the new DFU fallback and fail fast
  instead.

### Changed
- README expanded with the DFU fallback explanation, updated usage/options,
  and a documented USB-autosuspend false positive that can look identical to
  a genuine post-flash crash loop.

### Fixed
- N/A (no bugs in 1.0.0's core UF2 path — this release adds coverage for a
  bootloader mode it didn't previously handle)

## [1.0.0] - 2026-08-13

### Added
- Initial `heltec_reflash.py`: 1200bps touch to trigger a bootloader reset,
  wait for the UF2 mass-storage volume, copy the given `.uf2` file, confirm
  the device re-enumerates in application mode.
- Initial README.
