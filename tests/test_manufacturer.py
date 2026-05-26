from blu_battery.manufacturer import classify_address, identify_manufacturer
from blu_battery.models import AddressKind


def test_classify_static_random_address() -> None:
    assert classify_address("D4:36:39:12:34:56") == AddressKind.RANDOM_STATIC


def test_identifies_advertisement_company_id() -> None:
    info = identify_manufacturer("D4:36:39:12:34:56", {0x0075: b"demo"})

    assert info.company_ids[0x0075] == "Samsung Electronics"


def test_identifies_battery_advertisement_company_id() -> None:
    info = identify_manufacturer("50:AA:BB:CC:DD:EE", {0x0104: b"demo"})

    assert info.company_ids[0x0104] == "PLUS Location Systems"
