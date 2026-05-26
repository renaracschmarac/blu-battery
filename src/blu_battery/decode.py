from __future__ import annotations

from .models import GATTCharacteristic


BATTERY_LEVEL_UUID = "00002a19-0000-1000-8000-00805f9b34fb"
MANUFACTURER_NAME_UUID = "00002a29-0000-1000-8000-00805f9b34fb"
MODEL_NUMBER_UUID = "00002a24-0000-1000-8000-00805f9b34fb"
SERIAL_NUMBER_UUID = "00002a25-0000-1000-8000-00805f9b34fb"
HARDWARE_REVISION_UUID = "00002a27-0000-1000-8000-00805f9b34fb"
FIRMWARE_REVISION_UUID = "00002a26-0000-1000-8000-00805f9b34fb"


TEXT_CHARACTERISTICS = {
    MANUFACTURER_NAME_UUID: "Manufacturer name",
    MODEL_NUMBER_UUID: "Model number",
    SERIAL_NUMBER_UUID: "Serial number",
    HARDWARE_REVISION_UUID: "Hardware revision",
    FIRMWARE_REVISION_UUID: "Firmware revision",
}


def decode_stats(characteristics: list[GATTCharacteristic]) -> tuple[dict[str, str], list[str]]:
    stats: dict[str, str] = {}
    for characteristic in characteristics:
        if characteristic.value is None:
            continue
        uuid = characteristic.uuid.lower()
        if uuid == BATTERY_LEVEL_UUID and characteristic.value:
            stats["Battery level"] = f"{characteristic.value[0]}%"
        elif uuid in TEXT_CHARACTERISTICS:
            stats[TEXT_CHARACTERISTICS[uuid]] = _decode_text(characteristic.value)

    unavailable = [
        "Pack voltage",
        "Pack current",
        "State of charge from BMS protocol",
        "Cell voltages",
        "Temperatures",
        "Cycle count",
        "Fault and alarm registers",
    ]
    if "Battery level" in stats:
        unavailable.remove("State of charge from BMS protocol")
    return stats, unavailable


def format_bytes(value: bytes | None, limit: int = 24) -> str:
    if value is None:
        return ""
    raw = value[:limit].hex(" ")
    if len(value) > limit:
        return f"{raw} ..."
    return raw


def _decode_text(value: bytes) -> str:
    return value.decode("utf-8", errors="replace").strip("\x00\r\n ")
