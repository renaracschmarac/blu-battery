from pathlib import Path


FORBIDDEN = (
    "write_gatt_descriptor",
    "DALY_FUNCTION_WRITE",
    "write_register",
    ".pair(",
    ".unpair(",
)


def test_source_contains_no_forbidden_ble_operations() -> None:
    src_root = Path(__file__).resolve().parents[1] / "src"
    source = "\n".join(path.read_text() for path in src_root.rglob("*.py"))

    for token in FORBIDDEN:
        assert token not in source


def test_only_fixed_telemetry_write_is_exposed() -> None:
    ble_source = (
        Path(__file__).resolve().parents[1] / "src" / "blu_battery" / "ble.py"
    ).read_text()

    assert ble_source.count("write_gatt_char") == 1
    assert ble_source.count("start_notify") == 1
    assert "build_status_request()" in ble_source
