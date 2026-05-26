from __future__ import annotations

import re
from pathlib import Path

from .models import AddressKind, ManufacturerInfo


OUI_PATHS = (
    Path("/usr/share/ieee-data/oui.txt"),
    Path("/var/lib/ieee-data/oui.txt"),
    Path("/usr/share/misc/oui.txt"),
)

COMPANY_IDS: dict[int, str] = {
    0x0006: "Microsoft",
    0x000D: "Texas Instruments",
    0x004C: "Apple",
    0x0059: "Nordic Semiconductor",
    0x0075: "Samsung Electronics",
    0x00E0: "Google",
    0x0104: "PLUS Location Systems",
    0x0131: "Cypress Semiconductor",
    0x0171: "Dialog Semiconductor",
    0x0211: "Telink Semiconductor",
    0x02E5: "Espressif",
    0x030F: "STMicroelectronics",
    0x038F: "Qualcomm Technologies",
    0x046D: "MediaTek",
}


def classify_address(address: str) -> AddressKind:
    parts = _address_parts(address)
    if parts is None:
        return AddressKind.UNKNOWN
    first = int(parts[0], 16)
    marker = first & 0b1100_0000
    if marker == 0b1100_0000:
        return AddressKind.RANDOM_STATIC
    if marker == 0b0100_0000:
        return AddressKind.RANDOM_RESOLVABLE_PRIVATE
    if marker == 0:
        return AddressKind.RANDOM_NON_RESOLVABLE_PRIVATE
    return AddressKind.PUBLIC_STYLE


def identify_manufacturer(
    address: str, manufacturer_data: dict[int, bytes] | None = None
) -> ManufacturerInfo:
    address_kind = classify_address(address)
    oui = _oui_from_address(address) if address_kind == AddressKind.PUBLIC_STYLE else None
    company_ids = {
        company_id: COMPANY_IDS.get(company_id, f"Bluetooth company ID 0x{company_id:04X}")
        for company_id in (manufacturer_data or {})
    }
    return ManufacturerInfo(
        address_kind=address_kind,
        oui=oui,
        oui_vendor=_lookup_oui(oui) if oui else None,
        company_ids=company_ids,
    )


def _address_parts(address: str) -> list[str] | None:
    parts = address.upper().split(":")
    if len(parts) != 6 or any(not re.fullmatch(r"[0-9A-F]{2}", part) for part in parts):
        return None
    return parts


def _oui_from_address(address: str) -> str | None:
    parts = _address_parts(address)
    if parts is None:
        return None
    return "-".join(parts[:3])


def _lookup_oui(oui: str | None) -> str | None:
    if not oui:
        return None
    compact = oui.replace("-", "").upper()
    for path in OUI_PATHS:
        if not path.exists():
            continue
        vendor = _lookup_oui_file(path, compact)
        if vendor:
            return vendor
    return None


def _lookup_oui_file(path: Path, compact_oui: str) -> str | None:
    assignment = f"{compact_oui}     (base 16)"
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                if assignment in line:
                    return line.split("(base 16)", 1)[1].strip() or None
    except OSError:
        return None
    return None
