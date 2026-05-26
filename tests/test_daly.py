import asyncio
import sys
from types import SimpleNamespace

import pytest

from blu_battery.ble import TelemetryBatteryClient
from blu_battery.daly import (
    DALY_COMMAND_UUID,
    DALY_NOTIFY_UUID,
    DalyProtocolError,
    build_status_request,
    consume_status_frame,
    decode_status_response,
    modbus_crc16,
)
from blu_battery.models import BLEAdvertisement


def _status_response(
    voltage: float,
    current: float,
    remaining_capacity: float,
    cell_voltages: tuple[float, ...] = (),
) -> bytes:
    frame = bytearray([0xD2, 0x03, 62 * 2])
    frame.extend(bytes(62 * 2))
    for index, cell_voltage in enumerate(cell_voltages):
        frame[3 + index * 2 : 5 + index * 2] = round(cell_voltage * 1000).to_bytes(2, byteorder="big")
    frame[83:85] = round(voltage * 10).to_bytes(2, byteorder="big")
    frame[85:87] = round(current * 10 + 30000).to_bytes(2, byteorder="big")
    frame[99:101] = round(remaining_capacity * 10).to_bytes(2, byteorder="big")
    frame[102] = len(cell_voltages)
    frame.extend(modbus_crc16(frame).to_bytes(2, byteorder="little"))
    return bytes(frame)


def test_status_request_is_fixed_read_only_modbus_query() -> None:
    request = build_status_request()

    assert request[:6] == bytes.fromhex("d2 03 00 00 00 3e")
    assert int.from_bytes(request[-2:], byteorder="little") == modbus_crc16(request[:-2])


def test_decode_status_response_extracts_requested_telemetry() -> None:
    telemetry = decode_status_response(_status_response(55.4, -7.5, 14.3, (3.962, 3.958)))

    assert telemetry.voltage == pytest.approx(55.4)
    assert telemetry.current == pytest.approx(-7.5)
    assert telemetry.remaining_capacity == pytest.approx(14.3)
    assert telemetry.cell_voltages == pytest.approx((3.962, 3.958))
    assert telemetry.as_stats()["Pack current"] == "-7.5 A (discharging)"
    assert telemetry.as_stats()["Cell 01 voltage"] == "3.962 V"


def test_status_frame_accepts_fragmented_notifications() -> None:
    response = _status_response(54.2, 2.1, 18.0)
    buffer = bytearray()

    assert consume_status_frame(buffer, response[:20]) is None
    assert consume_status_frame(buffer, response[20:]) == response


def test_invalid_status_checksum_is_rejected() -> None:
    response = bytearray(_status_response(54.2, 2.1, 18.0))
    response[83] ^= 1

    try:
        decode_status_response(bytes(response))
    except DalyProtocolError as exc:
        assert "checksum" in str(exc)
    else:
        raise AssertionError("modified response must be rejected")


def test_client_reuses_subscription_for_repeated_allowlisted_status_queries() -> None:
    responses = [
        _status_response(55.1, 1.3, 12.8, (3.935,)),
        _status_response(55.0, -0.4, 12.7, (3.928,)),
    ]

    class FakeClient:
        callback = None
        notifications = 0
        writes = []

        async def start_notify(self, uuid, callback):
            assert uuid == DALY_NOTIFY_UUID
            self.notifications += 1
            self.callback = callback

        async def write_gatt_char(self, uuid, value, response=False):
            self.writes.append((uuid, value, response))
            self.callback(None, responses[len(self.writes) - 1])

    fake = FakeClient()
    client = TelemetryBatteryClient("battery")

    async def read_twice():
        channel = await client._subscribe_status(fake)
        return await client._request_status(fake, channel), await client._request_status(fake, channel)

    first, second = asyncio.run(read_twice())

    assert fake.notifications == 1
    assert fake.writes == [(DALY_COMMAND_UUID, build_status_request(), False)] * 2
    assert first["Pack voltage"] == "55.1 V"
    assert first["Cell 01 voltage"] == "3.935 V"
    assert second["Pack current"] == "-0.4 A (discharging)"


def test_monitor_refreshes_over_one_connection(monkeypatch) -> None:
    response = _status_response(58.0, 0.0, 20.0, (4.143, 4.141))

    class FakeBleakClient:
        enters = 0
        notifications = 0
        writes = 0

        def __init__(self, _address, timeout):
            self.services = []

        async def __aenter__(self):
            type(self).enters += 1
            return self

        async def __aexit__(self, *_args):
            return None

        async def start_notify(self, uuid, callback):
            assert uuid == DALY_NOTIFY_UUID
            type(self).notifications += 1
            self.callback = callback

        async def write_gatt_char(self, uuid, value, response=False):
            assert (uuid, value, response) == (DALY_COMMAND_UUID, build_status_request(), False)
            type(self).writes += 1
            self.callback(None, response_bytes)

    response_bytes = response
    monkeypatch.setitem(sys.modules, "bleak", SimpleNamespace(BleakClient=FakeBleakClient))
    client = TelemetryBatteryClient("battery")

    async def find_target():
        return BLEAdvertisement(name="battery", address="AA:BB:CC:DD:EE:FF")

    client.find_target = find_target

    async def collect_two():
        stream = client.samples(0)
        first = await anext(stream)
        second = await anext(stream)
        await stream.aclose()
        return first, second

    first, second = asyncio.run(collect_two())

    assert FakeBleakClient.enters == 1
    assert FakeBleakClient.notifications == 1
    assert FakeBleakClient.writes == 2
    assert first.stats["Cell 02 voltage"] == "4.141 V"
    assert second.stats["Pack voltage"] == "58.0 V"


def test_manual_address_bypasses_discovery_scan() -> None:
    client = TelemetryBatteryClient("battery", "AA:BB:CC:DD:EE:FF")

    async def fail_scan():
        raise AssertionError("explicit-address operation must not scan")

    client.scan = fail_scan
    target = asyncio.run(client.find_target())

    assert target.address == "AA:BB:CC:DD:EE:FF"
    assert target.name == "battery"
