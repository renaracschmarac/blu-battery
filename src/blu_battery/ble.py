from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import Any

from .daly import (
    DALY_COMMAND_UUID,
    DALY_NOTIFY_UUID,
    build_status_request,
    consume_status_frame,
    decode_status_response,
)
from .decode import decode_stats
from .manufacturer import identify_manufacturer
from .models import (
    BLEAdvertisement,
    BatterySample,
    GATTCharacteristic,
)


class BLEError(RuntimeError):
    pass


class ZeroWriteBatteryClient:
    """Read-only BLE access for a battery.

    This class intentionally exposes no methods for pairing, subscribing,
    descriptor changes, or characteristic writes.
    """

    def __init__(self, name: str, address: str | None = None, timeout: float = 12.0):
        self.name = name
        self.address = address
        self.timeout = timeout

    async def scan(self) -> list[BLEAdvertisement]:
        from bleak import BleakScanner

        try:
            discovered = await BleakScanner.discover(timeout=self.timeout, return_adv=True)
        except Exception as exc:
            raise BLEError(f"Bluetooth scan failed: {type(exc).__name__}: {exc}") from exc
        return [_advertisement_from_bleak(entry) for entry in _iter_discoveries(discovered)]

    async def find_target(self) -> BLEAdvertisement:
        if self.address:
            return BLEAdvertisement(name=self.name, address=self.address)

        devices = await self.scan()
        for device in devices:
            if device.name == self.name:
                return device
        lowered = self.name.lower()
        for device in devices:
            if device.name and device.name.lower() == lowered:
                return device
        raise BLEError(f"Bluetooth device name not found: {self.name}")

    async def collect_once(self) -> BatterySample:
        from bleak import BleakClient

        device = await self.find_target()
        characteristics: list[GATTCharacteristic] = []
        try:
            async with BleakClient(device.address, timeout=self.timeout) as client:
                services = client.services
                for service in services:
                    for characteristic in service.characteristics:
                        properties = tuple(characteristic.properties or ())
                        value: bytes | None = None
                        error: str | None = None
                        if "read" in properties:
                            try:
                                value = bytes(await client.read_gatt_char(characteristic.uuid))
                            except Exception as exc:
                                error = f"{type(exc).__name__}: {exc}"
                        characteristics.append(
                            GATTCharacteristic(
                                service_uuid=str(service.uuid),
                                uuid=str(characteristic.uuid),
                                description=characteristic.description,
                                properties=properties,
                                value=value,
                                error=error,
                            )
                        )
        except Exception as exc:
            raise BLEError(f"Bluetooth connection/read failed: {type(exc).__name__}: {exc}") from exc

        manufacturer = identify_manufacturer(device.address, device.manufacturer_data)
        stats, unavailable = decode_stats(characteristics)
        return BatterySample.now(device, manufacturer, characteristics, stats, unavailable)


class TelemetryBatteryClient(ZeroWriteBatteryClient):
    """Read BMS status with one allowlisted Daly query, without control commands."""

    async def collect_once(self) -> BatterySample:
        from bleak import BleakClient

        device = await self.find_target()
        try:
            async with BleakClient(device.address, timeout=self.timeout) as client:
                characteristics = await self._read_characteristics(client)
                status_channel = await self._subscribe_status(client)
                protocol_stats = await self._request_status(client, status_channel)
        except BLEError:
            raise
        except Exception as exc:
            raise BLEError(f"Bluetooth connection/read failed: {type(exc).__name__}: {exc}") from exc

        return self._sample(device, characteristics, protocol_stats)

    async def samples(self, interval: float):
        from bleak import BleakClient

        device = await self.find_target()
        try:
            async with BleakClient(device.address, timeout=self.timeout) as client:
                characteristics = await self._read_characteristics(client)
                status_channel = await self._subscribe_status(client)
                while True:
                    protocol_stats = await self._request_status(client, status_channel)
                    yield self._sample(device, characteristics, protocol_stats)
                    await asyncio.sleep(interval)
        except BLEError:
            raise
        except Exception as exc:
            raise BLEError(f"Bluetooth connection/read failed: {type(exc).__name__}: {exc}") from exc

    async def _read_characteristics(self, client: Any) -> list[GATTCharacteristic]:
        characteristics: list[GATTCharacteristic] = []
        for service in client.services:
            for characteristic in service.characteristics:
                properties = tuple(characteristic.properties or ())
                value: bytes | None = None
                error: str | None = None
                if "read" in properties:
                    try:
                        value = bytes(await client.read_gatt_char(characteristic.uuid))
                    except Exception as exc:
                        error = f"{type(exc).__name__}: {exc}"
                characteristics.append(
                    GATTCharacteristic(
                        service_uuid=str(service.uuid),
                        uuid=str(characteristic.uuid),
                        description=characteristic.description,
                        properties=properties,
                        value=value,
                        error=error,
                    )
                )
        return characteristics

    def _sample(
        self,
        device: BLEAdvertisement,
        characteristics: list[GATTCharacteristic],
        protocol_stats: dict[str, str],
    ) -> BatterySample:
        manufacturer = identify_manufacturer(device.address, device.manufacturer_data)
        stats, unavailable = decode_stats(characteristics)
        stats.update(protocol_stats)
        available = {"Pack voltage", "Pack current"}
        if any(name.startswith("Cell ") for name in protocol_stats):
            available.add("Cell voltages")
        unavailable = [item for item in unavailable if item not in available]
        return BatterySample.now(device, manufacturer, characteristics, stats, unavailable)

    async def _subscribe_status(self, client: Any) -> dict[str, Any]:
        received = bytearray()
        status_channel: dict[str, Any] = {"received": received, "response": None}

        def callback(_sender: Any, chunk: bytearray) -> None:
            frame = consume_status_frame(received, bytes(chunk))
            response = status_channel["response"]
            if frame is not None and response is not None and not response.done():
                response.set_result(frame)

        await client.start_notify(DALY_NOTIFY_UUID, callback)
        return status_channel

    async def _request_status(self, client: Any, status_channel: dict[str, Any]) -> dict[str, str]:
        status_channel["received"].clear()
        response: asyncio.Future[bytes] = asyncio.get_running_loop().create_future()
        status_channel["response"] = response
        await client.write_gatt_char(DALY_COMMAND_UUID, build_status_request(), response=False)
        try:
            frame = await asyncio.wait_for(response, timeout=self.timeout)
        except TimeoutError as exc:
            raise BLEError("Timed out waiting for Daly BMS status response") from exc
        finally:
            status_channel["response"] = None
        return decode_status_response(frame).as_stats()


class FakeBatteryClient:
    def __init__(self) -> None:
        self.device = BLEAdvertisement(
            name="52v20ah Samsung 50s",
            address="D4:36:39:12:34:56",
            rssi=-48,
            manufacturer_data={0x0075: b"\x01\x02demo"},
            service_uuids=["0000180f-0000-1000-8000-00805f9b34fb"],
        )

    async def scan(self) -> list[BLEAdvertisement]:
        await asyncio.sleep(0)
        return [self.device]

    async def find_target(self) -> BLEAdvertisement:
        await asyncio.sleep(0)
        return self.device

    async def collect_once(self) -> BatterySample:
        await asyncio.sleep(0)
        characteristics = [
            GATTCharacteristic(
                service_uuid="0000180f-0000-1000-8000-00805f9b34fb",
                uuid="00002a19-0000-1000-8000-00805f9b34fb",
                description="Battery Level",
                properties=("read",),
                value=bytes([82]),
            ),
            GATTCharacteristic(
                service_uuid="0000180a-0000-1000-8000-00805f9b34fb",
                uuid="00002a29-0000-1000-8000-00805f9b34fb",
                description="Manufacturer Name String",
                properties=("read",),
                value=b"100Balance",
            ),
        ]
        manufacturer = identify_manufacturer(self.device.address, self.device.manufacturer_data)
        stats, unavailable = decode_stats(characteristics)
        return BatterySample.now(self.device, manufacturer, characteristics, stats, unavailable)

    async def samples(self, interval: float):
        while True:
            yield await self.collect_once()
            await asyncio.sleep(interval)


def _iter_discoveries(discovered: Any) -> Iterable[Any]:
    if isinstance(discovered, dict):
        return discovered.values()
    return discovered


def _advertisement_from_bleak(entry: Any) -> BLEAdvertisement:
    if isinstance(entry, tuple):
        device, adv = entry
    else:
        device, adv = entry, None

    name = getattr(adv, "local_name", None) if adv is not None else None
    if not name:
        name = getattr(device, "name", None)

    metadata = getattr(device, "metadata", {}) or {}
    manufacturer_data = dict(getattr(adv, "manufacturer_data", None) or {})
    if not manufacturer_data:
        manufacturer_data = dict(metadata.get("manufacturer_data", {}) or {})

    service_uuids = list(getattr(adv, "service_uuids", None) or metadata.get("uuids", []) or [])
    rssi = getattr(adv, "rssi", None)
    if rssi is None:
        rssi = getattr(device, "rssi", None)

    return BLEAdvertisement(
        name=name,
        address=str(getattr(device, "address")),
        rssi=rssi,
        manufacturer_data=manufacturer_data,
        service_uuids=[str(uuid) for uuid in service_uuids],
        raw={"details": repr(getattr(device, "details", ""))},
    )
