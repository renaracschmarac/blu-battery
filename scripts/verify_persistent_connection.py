from __future__ import annotations

import argparse
import asyncio
from contextlib import suppress
import subprocess
import time
from datetime import datetime

from blu_battery.ble import TelemetryBatteryClient


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Log repeated BMS reads while verifying that BlueZ reports one ongoing connection."
    )
    parser.add_argument("--address", required=True, help="BLE address of the battery")
    parser.add_argument("--seconds", type=float, default=300.0, help="test duration in seconds")
    parser.add_argument("--interval", type=float, default=1.0, help="seconds between logged samples")
    parser.add_argument("--timeout", type=float, default=20.0, help="BLE response timeout in seconds")
    return parser.parse_args()


async def run(args: argparse.Namespace) -> int:
    client = TelemetryBatteryClient("52v20ah Samsung 50S", args.address, args.timeout)
    started = time.monotonic()
    deadline = started + args.seconds
    count = 0
    disconnected = 0
    error: str | None = None
    stream = client.samples(args.interval)
    try:
        while True:
            sample = await anext(stream)
            count += 1
            elapsed = time.monotonic() - started
            connected = connection_state(args.address)
            if connected != "yes":
                disconnected += 1
            cells = len([key for key in sample.stats if key.startswith("Cell ")])
            timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
            print(
                f"{timestamp} elapsed={elapsed:0.1f}s connected={connected} "
                f"voltage={sample.stats.get('Pack voltage')} "
                f"current={sample.stats.get('Pack current')} "
                f"remaining={sample.stats.get('Capacity remaining')} cells={cells}",
                flush=True,
            )
            if time.monotonic() >= deadline:
                break
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        print(
            f"{datetime.now().astimezone().isoformat(timespec='seconds')} "
            f"elapsed={time.monotonic() - started:0.1f}s connected={connection_state(args.address)} "
            f"error={error}",
            flush=True,
        )
    finally:
        with suppress(Exception):
            await stream.aclose()

    elapsed = time.monotonic() - started
    result = "PASS" if error is None and disconnected == 0 and elapsed >= args.seconds else "FAIL"
    suffix = "" if error is None else f" error={error}"
    print(f"{result} elapsed={elapsed:0.1f}s samples={count} disconnected_samples={disconnected}{suffix}")
    return 0 if result == "PASS" else 1


def connection_state(address: str) -> str:
    completed = subprocess.run(
        ["bluetoothctl", "info", address],
        capture_output=True,
        check=False,
        text=True,
    )
    for line in completed.stdout.splitlines():
        key, separator, value = line.strip().partition(":")
        if separator and key == "Connected":
            return value.strip()
    return "unknown"


def main() -> int:
    return asyncio.run(run(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
