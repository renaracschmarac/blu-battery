from blu_battery.decode import decode_stats
from blu_battery.models import GATTCharacteristic


def test_decode_standard_battery_level() -> None:
    stats, unavailable = decode_stats(
        [
            GATTCharacteristic(
                service_uuid="0000180f-0000-1000-8000-00805f9b34fb",
                uuid="00002a19-0000-1000-8000-00805f9b34fb",
                description="Battery Level",
                properties=("read",),
                value=bytes([77]),
            )
        ]
    )

    assert stats["Battery level"] == "77%"
    assert "State of charge from BMS protocol" not in unavailable


def test_decode_device_information_text() -> None:
    stats, _ = decode_stats(
        [
            GATTCharacteristic(
                service_uuid="0000180a-0000-1000-8000-00805f9b34fb",
                uuid="00002a29-0000-1000-8000-00805f9b34fb",
                description="Manufacturer Name String",
                properties=("read",),
                value=b"100Balance\x00",
            )
        ]
    )

    assert stats["Manufacturer name"] == "100Balance"
