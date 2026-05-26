from __future__ import annotations

from dataclasses import dataclass


DALY_NOTIFY_UUID = "0000fff1-0000-1000-8000-00805f9b34fb"
DALY_COMMAND_UUID = "0000fff2-0000-1000-8000-00805f9b34fb"
STATUS_RESPONSE_PAYLOAD_LENGTHS = (62 * 2, 80 * 2)


class DalyProtocolError(ValueError):
    pass


@dataclass(frozen=True)
class DalyTelemetry:
    voltage: float
    current: float
    remaining_capacity: float
    cell_voltages: tuple[float, ...]

    def as_stats(self) -> dict[str, str]:
        if self.current > 0:
            flow = "charging"
        elif self.current < 0:
            flow = "discharging"
        else:
            flow = "idle"
        stats = {
            "Pack voltage": f"{self.voltage:.1f} V",
            "Pack current": f"{self.current:.1f} A ({flow})",
            "Capacity remaining": f"{self.remaining_capacity:.1f} Ah",
        }
        for index, voltage in enumerate(self.cell_voltages, start=1):
            stats[f"Cell {index:02d} voltage"] = f"{voltage:.3f} V"
        return stats


def build_status_request() -> bytes:
    """Build the only BMS command this app sends: read status registers 0x00-0x3D."""
    frame = bytes((0xD2, 0x03, 0x00, 0x00, 0x00, 0x3E))
    checksum = modbus_crc16(frame)
    return frame + checksum.to_bytes(2, byteorder="little")


def consume_status_frame(buffer: bytearray, chunk: bytes) -> bytes | None:
    buffer.extend(chunk)
    try:
        start = buffer.index(0xD2)
    except ValueError:
        buffer.clear()
        return None
    if start:
        del buffer[:start]
    if len(buffer) < 3:
        return None
    size = 3 + buffer[2] + 2
    if len(buffer) < size:
        return None
    return bytes(buffer[:size])


def decode_status_response(frame: bytes) -> DalyTelemetry:
    if len(frame) < 3 or frame[0:2] != b"\xD2\x03":
        raise DalyProtocolError("not a Daly status response")
    if frame[2] not in STATUS_RESPONSE_PAYLOAD_LENGTHS:
        raise DalyProtocolError(f"unexpected status response length: {frame[2]}")
    expected_size = 3 + frame[2] + 2
    if len(frame) != expected_size:
        raise DalyProtocolError("incomplete status response")
    expected_crc = modbus_crc16(frame[:-2])
    received_crc = int.from_bytes(frame[-2:], byteorder="little")
    if received_crc != expected_crc:
        raise DalyProtocolError("invalid status response checksum")

    cell_count = min(frame[102], 32)
    return DalyTelemetry(
        voltage=_uint16(frame, 83) * 0.1,
        current=(_uint16(frame, 85) - 30000) * 0.1,
        remaining_capacity=_uint16(frame, 99) * 0.1,
        cell_voltages=tuple(_uint16(frame, 3 + (index * 2)) * 0.001 for index in range(cell_count)),
    )


def modbus_crc16(value: bytes) -> int:
    checksum = 0xFFFF
    for byte in value:
        checksum ^= byte
        for _ in range(8):
            if checksum & 0x0001:
                checksum = (checksum >> 1) ^ 0xA001
            else:
                checksum >>= 1
    return checksum


def _uint16(value: bytes, offset: int) -> int:
    return int.from_bytes(value[offset : offset + 2], byteorder="big")
