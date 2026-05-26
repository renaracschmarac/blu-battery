from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence

from .ble import BLEError, FakeBatteryClient, TelemetryBatteryClient
from .decode import format_bytes
from .models import BLEAdvertisement, BatterySample, DEFAULT_DEVICE_NAME


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        return asyncio.run(_async_main(args))
    except KeyboardInterrupt:
        return 130


async def _async_main(args: argparse.Namespace) -> int:
    client = FakeBatteryClient() if args.fake else TelemetryBatteryClient(args.name, args.address, args.timeout)
    if args.command == "scan":
        try:
            devices = await client.scan()
        except BLEError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 2
        _print_scan(devices)
        return 0

    if args.once:
        try:
            sample = await client.collect_once()
        except BLEError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 2
        _print_sample(sample)
        return 0

    await _live_dashboard(client, args.interval)
    return 0


async def _live_dashboard(client: TelemetryBatteryClient | FakeBatteryClient, interval: float) -> None:
    try:
        from rich.console import Console
        from rich.live import Live
    except ImportError:
        try:
            async for sample in client.samples(interval):
                _print_sample(sample)
        except Exception as exc:
            print(f"Error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return

    console = Console()
    with Live(console=console, refresh_per_second=4, screen=False) as live:
        try:
            async for sample in client.samples(interval):
                live.update(_render_sample(sample))
        except Exception as exc:
            live.update(f"[red]Error:[/red] {type(exc).__name__}: {exc}")


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Telemetry-only Bluetooth monitor for an e-bike battery."
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=("monitor", "scan"),
        default="monitor",
        help="run the monitor or list nearby BLE devices",
    )
    parser.add_argument("--name", default=DEFAULT_DEVICE_NAME, help="BLE local name to find")
    parser.add_argument("--address", help="manual BLE address override")
    parser.add_argument("--timeout", type=float, default=12.0, help="scan/connect timeout in seconds")
    parser.add_argument("--interval", type=float, default=1.0, help="refresh interval in seconds")
    parser.add_argument("--once", action="store_true", help="collect one sample and exit")
    parser.add_argument("--fake", action="store_true", help="use a fake battery sample")
    return parser.parse_args(argv)


def _print_scan(devices: list[BLEAdvertisement]) -> None:
    if not devices:
        print("No BLE devices found.")
        return
    for device in sorted(devices, key=lambda item: (item.name or "", item.address)):
        name = device.name or "(unnamed)"
        rssi = "" if device.rssi is None else f" RSSI={device.rssi}"
        print(f"{device.address} {name}{rssi}")


def _print_sample(sample: BatterySample) -> None:
    print(f"Device: {sample.device.name or '(unnamed)'} {sample.device.address}")
    print(f"RSSI: {sample.device.rssi if sample.device.rssi is not None else 'unknown'}")
    print(f"Address kind: {sample.manufacturer.address_kind.value}")
    if sample.manufacturer.oui:
        print(f"OUI: {sample.manufacturer.oui} {sample.manufacturer.oui_vendor or '(vendor unknown)'}")
    if sample.manufacturer.company_ids:
        companies = ", ".join(sample.manufacturer.company_ids.values())
        print(f"Advertisement company IDs: {companies}")
    print("Stats:")
    if sample.stats:
        for name, value in sample.stats.items():
            print(f"  {name}: {value}")
    else:
        print("  No BMS telemetry was returned.")
    print("Unavailable in this sample:")
    for item in sample.unavailable:
        print(f"  {item}")
    print("Readable GATT values:")
    for characteristic in sample.characteristics:
        if characteristic.value is not None:
            print(f"  {characteristic.uuid} {characteristic.description}: {format_bytes(characteristic.value)}")
        elif characteristic.error:
            print(f"  {characteristic.uuid} {characteristic.description}: {characteristic.error}")


def _render_sample(sample: BatterySample):
    from rich.console import Group
    from rich.panel import Panel
    from rich.table import Table

    overview = Table.grid(padding=(0, 2))
    overview.add_column(style="bold")
    overview.add_column()
    overview.add_row("Device", f"{sample.device.name or '(unnamed)'} {sample.device.address}")
    overview.add_row("RSSI", str(sample.device.rssi if sample.device.rssi is not None else "unknown"))
    overview.add_row("Address", sample.manufacturer.address_kind.value)
    if sample.manufacturer.oui:
        overview.add_row("OUI", f"{sample.manufacturer.oui} {sample.manufacturer.oui_vendor or '(vendor unknown)'}")
    if sample.manufacturer.company_ids:
        overview.add_row("Company IDs", ", ".join(sample.manufacturer.company_ids.values()))

    stats = Table(title="Stats")
    stats.add_column("Name")
    stats.add_column("Value")
    if sample.stats:
        for name, value in sample.stats.items():
            stats.add_row(name, value)
    else:
        stats.add_row("Readable standard battery stats", "none found")

    unavailable = Table(title="Unavailable In This Sample")
    unavailable.add_column("Metric")
    for item in sample.unavailable:
        unavailable.add_row(item)

    gatt = Table(title="Readable GATT Values")
    gatt.add_column("UUID", overflow="fold")
    gatt.add_column("Description")
    gatt.add_column("Value / Error", overflow="fold")
    for characteristic in sample.characteristics:
        if characteristic.value is not None:
            value = format_bytes(characteristic.value)
        elif characteristic.error:
            value = characteristic.error
        else:
            continue
        gatt.add_row(characteristic.uuid, characteristic.description, value)

    return Group(
        Panel(overview, title="blu-battery telemetry monitor"),
        stats,
        unavailable,
        gatt,
    )


if __name__ == "__main__":
    raise SystemExit(main())
