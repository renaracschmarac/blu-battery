from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


DEFAULT_DEVICE_NAME = "52v20ah Samsung 50s"


class AddressKind(str, Enum):
    PUBLIC_STYLE = "public-style"
    RANDOM_STATIC = "random-static"
    RANDOM_RESOLVABLE_PRIVATE = "random-resolvable-private"
    RANDOM_NON_RESOLVABLE_PRIVATE = "random-non-resolvable-private"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ManufacturerInfo:
    address_kind: AddressKind
    oui: str | None = None
    oui_vendor: str | None = None
    company_ids: dict[int, str] = field(default_factory=dict)


@dataclass(frozen=True)
class BLEAdvertisement:
    name: str | None
    address: str
    rssi: int | None = None
    manufacturer_data: dict[int, bytes] = field(default_factory=dict)
    service_uuids: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GATTCharacteristic:
    service_uuid: str
    uuid: str
    description: str
    properties: tuple[str, ...]
    value: bytes | None = None
    error: str | None = None


@dataclass(frozen=True)
class BatterySample:
    collected_at: datetime
    device: BLEAdvertisement
    manufacturer: ManufacturerInfo
    characteristics: list[GATTCharacteristic]
    stats: dict[str, str]
    unavailable: list[str]

    @classmethod
    def now(
        cls,
        device: BLEAdvertisement,
        manufacturer: ManufacturerInfo,
        characteristics: list[GATTCharacteristic],
        stats: dict[str, str],
        unavailable: list[str],
    ) -> "BatterySample":
        return cls(
            collected_at=datetime.now(timezone.utc),
            device=device,
            manufacturer=manufacturer,
            characteristics=characteristics,
            stats=stats,
            unavailable=unavailable,
        )
