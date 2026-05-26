# blu-battery

Telemetry-only Linux terminal monitor for the Bluetooth e-bike battery named
`52v20ah Samsung 50s`.

The app permits only the minimum BLE protocol traffic necessary to retrieve
operating telemetry from the `100 Balance` / Daly-family BMS:

- subscribe to the BMS response characteristic (`FFF1`)
- send a fixed Modbus read-status request (`D2 03 00 00 00 3E ...`) on `FFF2`

The app intentionally has:

- no arbitrary BMS write API
- no Modbus write-register commands
- no pairing or bonding
- no control/config/power commands

The status query retrieves pack voltage, charge/discharge current, and remaining
capacity in Ah, plus individual cell voltages, without changing BMS
configuration or switching power paths. In monitor mode the app connects once,
subscribes once, and refreshes telemetry on the existing BLE connection.

## Requirements

### Linux Monitor And Python Tests

- Linux host with Bluetooth Low Energy hardware and BlueZ available.
- Python `3.12` or newer with `venv` and `pip`.
- Python runtime packages installed from `pyproject.toml`: `bleak>=0.22` and
  `rich>=13.7`.
- Python test dependency: `pytest>=8.0`, installed by using the `dev` extra.
- `bluetoothctl` from BlueZ for persistent-connection verification.
- `btmon` from BlueZ tools is optional for protocol-level observation.
- A compatible Daly-family BLE BMS advertising the `FFF0` service/profile for
  live hardware testing. Unit tests and `--fake` mode do not require hardware.

The Linux BLE process and the Android app must not connect to the same BMS at
the same time.

### Android Build And Device Testing

- JDK `17`.
- Gradle compatible with Android Gradle Plugin `8.13.0`; the app was verified
  with Gradle `8.14.3`.
- Android SDK Platform `35` and Android SDK Build Tools installed.
- Android SDK Platform Tools, including `adb`, for phone installation and log
  verification.
- An Android device with Bluetooth Low Energy support running Android `6.0`
  (API `23`) or newer. The app targets API `35`.
- USB debugging authorized on the test phone when installing or inspecting the
  app with `adb`.
- Bluetooth permission approval in the app on first launch; Android `6` through
  `11` also require location permission for BLE scanning.

This repository does not commit a Gradle wrapper. Install Gradle separately or
use a trusted Gradle wrapper already provisioned in your Android development
environment.

## Install

Create a Python virtual environment and install the Linux monitor and tests:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
```

Run the automated Python tests:

```bash
.venv/bin/python -m pytest -q
```

Build the Android debug APK after the Android requirements above are installed:

```bash
gradle -p android-app --no-daemon assembleDebug
```

## Run

Continuously monitor by the advertised device name:

```bash
blu-battery
```

For commands that connect directly, set the address found by `blu-battery
scan`. The example address below is synthetic:

```bash
export BATTERY_ADDRESS="50:AA:BB:CC:DD:EE"
```

Continuously monitor the known battery directly, refreshing every second:

```bash
blu-battery --address "$BATTERY_ADDRESS" --interval 1
```

Using `--address` skips discovery and connects directly to the known battery.
Continuous monitor mode holds one BLE connection open, enables the `FFF1`
response subscription once, and sends the fixed telemetry status query at each
`--interval` refresh. The validated default refresh is one second; a ten-second
diagnostic interval caused this battery to disconnect after approximately 21
seconds. Stop the monitor with `Ctrl-C`.

Collect one telemetry sample, then disconnect:

```bash
blu-battery --address "$BATTERY_ADDRESS" --once
```

Scan for nearby advertisements without connecting:

```bash
blu-battery scan
```

Run with the fake device for UI/testing:

```bash
blu-battery --fake
```

## Verify Persistent Monitoring

Run the monitor in one terminal:

```bash
.venv/bin/blu-battery --address "$BATTERY_ADDRESS" --interval 1
```

The display should continuously refresh `Pack voltage`, `Pack current`,
`Capacity remaining`, and `Cell 01 voltage` through `Cell 14 voltage`.

While it is running, check BlueZ from another terminal:

```bash
bluetoothctl info "$BATTERY_ADDRESS" | grep Connected
```

It should report:

```text
Connected: yes
```

For protocol-level verification, capture Bluetooth events while running the
monitor:

```bash
sudo btmon
```

You should observe one initial LE connection and repeated writes of the same
read-status request on the open connection. You should not observe a repeated
connect/disconnect cycle per refresh.

### Five-Minute Logged Test

Run the bundled soak check from the project directory:

```bash
mkdir -p logs
PYTHONPATH=src .venv/bin/python -u scripts/verify_persistent_connection.py \
  --address "$BATTERY_ADDRESS" --seconds 300 --interval 1 \
  | tee logs/persistent-connection-5m.log
```

This opens the same persistent telemetry stream used by monitor mode. Every
second it logs the BlueZ `Connected` state, pack voltage/current/capacity, and
the reported cell count while reusing the open BLE connection.

A successful result ends with:

```text
PASS elapsed=... samples=... disconnected_samples=0
```

All logged samples must show `connected=yes`. Any `connected=no`,
`connected=unknown`, or final `FAIL ... error=...` indicates that the
persistence check failed or could not query BlueZ state.

Validated locally on May 25, 2026 with the command above:

```text
PASS elapsed=303.1s samples=243 disconnected_samples=0
```

The raw log is retained locally rather than committed because it contains
time-stamped battery telemetry. In the validation run, all 243 connection
samples reported `connected=yes` and 14 cell voltage readings were available
throughout the run.

## Android Monitor

The Android app in `android-app/` provides a portrait, full-screen display with
three equal bands: `VOLTAGE`, `CURRENT`, and `REMAINING`. While this monitor
screen is in the foreground, it keeps the phone display awake so Android does
not time out and lock the screen during monitoring. On first use it scans for
Daly-compatible BMS candidates using the observed advertisement marker, an
advertised telemetry service, or the known advertised name
`52v20ah Samsung 50s` as a bootstrap hint. A name match alone is not treated
as proof of a supported battery: the app requires the `FFF0` service with
`FFF1` and `FFF2` characteristics and a valid Daly telemetry response before
remembering the Bluetooth address or showing live data. It establishes one BLE
connection, subscribes once to `FFF1`, and sends only the fixed read-status
request on `FFF2` five times per second.

If one BMS candidate is detected, the app selects it for protocol validation
automatically. If multiple candidates are detected, it shows a device selection
list including name, address, and signal level. After a successful validated
connection and telemetry response, the Bluetooth address is stored for a faster
direct connection at subsequent app starts. If a stored-address connection
fails, the app returns to discovery and validation. Use `SETTINGS` > `Re-scan
for battery` to discard the remembered selection and find/select a different
BMS.

The `CURRENT` band changes color as current changes: it is dark green at
`0 A`, yellow at half the configured current magnitude, and bright red at the
configured full-scale current. The sign convention observed during charging is
positive for current into the pack and negative for current out of the pack.
Tap `SETTINGS` in the upper-right corner to change the persistent magnitude
limits:

- `Amps OUT (-)` defaults to `100 A`.
- `Amps IN (+)` defaults to `20 A`.

Samples at or above either limit stay bright red. Changing the display scale
does not send configuration or control commands to the BMS.

Before opening the Android app, stop the Linux monitor and confirm the laptop is
not holding the battery connection:

```bash
bluetoothctl info "$BATTERY_ADDRESS" | grep Connected
```

It must report `Connected: no` or that the device is not available before the
phone attempts to connect.

Build, install, and start the debug app on an attached Android phone:

```bash
gradle -p android-app --no-daemon assembleDebug
adb install -r android-app/app/build/outputs/apk/debug/app-debug.apk
adb shell am start -n com.blubattery.monitor/.MainActivity
```

Accept the Bluetooth permission prompt on first launch. For verification, read
live samples from Android logs:

```bash
adb logcat -s BluBattery:I '*:S'
```

The app logs `connected`, then repeating telemetry lines such as
`telemetry voltage=<volts>V current=<amps>A remaining=<amp-hours>Ah` while the
phone retains the BLE connection.

The default Android refresh interval is `200 ms` (`5 Hz`). For diagnostics, an
alternate interval can be set when launching over ADB:

```bash
adb shell am force-stop com.blubattery.monitor
adb shell am start -n com.blubattery.monitor/.MainActivity \
  --ei poll_interval_ms 200
```

Validated on an attached Android API 35 phone on May 25, 2026 after confirming
that the laptop did not have a battery connection.
The installed debug app connected and reported repeating telemetry samples
without a disconnect event.

Rate testing on the same phone and BMS established `200 ms` as the fastest
cleanly verified polling setting:

- `200 ms` (`5 Hz`): 404 decoded samples in the validation capture, with no
  disconnect or request failure.
- `180 ms` (requested `5.6 Hz`): a GATT disconnect occurred before recovery;
  after reconnect it did not produce a meaningful sustained improvement.
- `150 ms` (requested `6.7 Hz`): remained connected after startup but delivered
  only about `3.5 Hz`, so requests were outpacing usable responses.
- `100 ms` (requested `10 Hz`): logged a GATT disconnect and delivered only 52
  samples during the screening capture.

The final installed build, launched without an interval override, logged
`poll_interval_ms=200` and delivered 138 telemetry samples in approximately
28.1 seconds after connecting (about `4.9 Hz`) with no failure or disconnect.

## Notes

If Bluetooth discovery fails on Linux, check that BlueZ is running and that the
current user/session can access the system D-Bus Bluetooth service. Also make
sure the phone app is not connected to the BMS at the same time.

On the first local scan, this battery appeared as:

```text
<private-address> 52v20ah Samsung 50S
```

Its address is a BLE private/resolvable-style address, so the MAC prefix is not
a reliable manufacturer identity. Its advertisement manufacturer-data company ID
was `0x0104`, which is a Bluetooth SIG company identifier for the BLE
advertiser, not proof of who built the battery pack or cells. The Android app
uses that observed advertisement marker only to locate candidates and validates
the Daly telemetry GATT profile before storing or monitoring a selected device.
