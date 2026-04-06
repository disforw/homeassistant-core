"""Tests for QNAP sensor platform."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from homeassistant.components.qnap.const import (
    DEFAULT_PORT,
    DEFAULT_SSL,
    DEFAULT_TIMEOUT,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
)
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SSL,
    CONF_TIMEOUT,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant

from tests.common import MockConfigEntry

TEST_NAS_NAME = "Test NAS"
TEST_SERIAL = "QX1234567"

ENTRY_DATA = {
    CONF_HOST: "1.2.3.4",
    CONF_USERNAME: "admin",
    CONF_PASSWORD: "password",
    CONF_SSL: DEFAULT_SSL,
    CONF_VERIFY_SSL: DEFAULT_VERIFY_SSL,
    CONF_PORT: DEFAULT_PORT,
    CONF_TIMEOUT: DEFAULT_TIMEOUT,
}


def _make_system_stats(
    nic_name: str = "eth0",
    drive_name: str = "HDD 1",
) -> dict[str, Any]:
    """Return a minimal but complete system_stats payload."""
    return {
        "system": {
            "name": TEST_NAS_NAME,
            "model": "TS-453D",
            "serial_number": TEST_SERIAL,
            "temp_c": 40,
        },
        "cpu": {
            "temp_c": 55,
            "usage_percent": 10.0,
        },
        "memory": {
            "total": 8192,
            "free": 4096,
        },
        "firmware": {
            "version": "5.1.0.2548",
            "build": "20230101",
            "patch": "0",
        },
        "nics": {
            nic_name: {
                "link_status": "Up",
                "max_speed": 1000,
                "err_packets": 0,
                "ip": "192.168.1.10",
                "mac": "00:11:22:33:44:55",
                "mask": "255.255.255.0",
            }
        },
        "uptime": {
            "days": 1,
            "hours": 2,
            "minutes": 3,
            "seconds": 4,
        },
    }


def _make_coordinator_data(
    *,
    firmware_update: str | None = None,
    nic_name: str = "eth0",
    drive_name: str = "HDD 1",
    drive_temp_c: int | None = 35,
    include_bandwidth: bool = True,
) -> dict[str, Any]:
    """Build a full coordinator data dict for testing."""
    bandwidth: dict[str, Any] = {}
    if include_bandwidth:
        bandwidth[nic_name] = {"tx": 1000, "rx": 2000}

    return {
        "system_stats": _make_system_stats(nic_name=nic_name, drive_name=drive_name),
        "system_health": "OK",
        "smart_drive_health": {
            drive_name: {
                "health": "good",
                "temp_c": drive_temp_c,
                "drive_number": "0",
                "model": "TOSHIBA HDWD110",
                "serial": "X8ABC12345",
                "type": "HDD",
            }
        },
        "volumes": {
            "DataVol1": {
                "free_size": 500000000000,
                "total_size": 1000000000000,
            }
        },
        "bandwidth": bandwidth,
        "firmware_update": firmware_update,
    }


async def _setup_integration(
    hass: HomeAssistant,
    coordinator_data: dict[str, Any],
) -> MockConfigEntry:
    """Set up a QNAP entry with a fully controlled coordinator response."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=TEST_SERIAL,
        data=ENTRY_DATA,
    )
    entry.add_to_hass(hass)

    with patch(
        "homeassistant.components.qnap.coordinator.QNAPStats", autospec=True
    ) as mock_class:
        mock_instance = mock_class.return_value
        mock_instance.get_system_stats.return_value = coordinator_data["system_stats"]
        mock_instance.get_system_health.return_value = coordinator_data["system_health"]
        mock_instance.get_smart_disk_health.return_value = coordinator_data[
            "smart_drive_health"
        ]
        mock_instance.get_volumes.return_value = coordinator_data["volumes"]
        mock_instance.get_bandwidth.return_value = coordinator_data["bandwidth"]
        mock_instance.get_firmware_update.return_value = coordinator_data[
            "firmware_update"
        ]

        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    return entry


# ---------------------------------------------------------------------------
# Firmware update sensor
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_firmware_update_sensor_no_update(hass: HomeAssistant) -> None:
    """Firmware update sensor should be unknown/unavailable when get_firmware_update() returns None."""
    data = _make_coordinator_data(firmware_update=None)
    await _setup_integration(hass, data)

    state = hass.states.get("sensor.test_nas_firmware_update")
    assert state is not None
    # None native_value → HA reports unknown, not a crash or "0"
    assert state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE)


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_firmware_update_sensor_update_available(hass: HomeAssistant) -> None:
    """Firmware update sensor should report the version string returned by the API."""
    firmware_version = "5.2.0.1234 Build 20240101"
    data = _make_coordinator_data(firmware_update=firmware_version)
    await _setup_integration(hass, data)

    state = hass.states.get("sensor.test_nas_firmware_update")
    assert state is not None
    assert state.state == firmware_version


# ---------------------------------------------------------------------------
# Drive temperature sensor
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_drive_temp_sensor_none_returns_unknown(hass: HomeAssistant) -> None:
    """Drive temp sensor must return None (unknown), NOT 0, when temp_c is None."""
    data = _make_coordinator_data(drive_temp_c=None)
    await _setup_integration(hass, data)

    # Entity ID: device "Test NAS" + entity name "Drive HDD 1 temperature"
    state = hass.states.get("sensor.test_nas_drive_hdd_1_temperature")
    assert state is not None
    assert state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE), (
        f"Expected unknown/unavailable for None temp, got: {state.state!r}"
    )
    assert state.state != "0", "drive_temp must not return 0 when temp_c is None"


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_drive_temp_sensor_with_value(hass: HomeAssistant) -> None:
    """Drive temp sensor returns the integer temperature when temp_c is set."""
    data = _make_coordinator_data(drive_temp_c=38)
    await _setup_integration(hass, data)

    state = hass.states.get("sensor.test_nas_drive_hdd_1_temperature")
    assert state is not None
    assert state.state == "38"


# ---------------------------------------------------------------------------
# Network bandwidth sensors
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_network_sensor_nic_missing_from_bandwidth(hass: HomeAssistant) -> None:
    """Network tx/rx sensors return None (not KeyError) when NIC absent from bandwidth."""
    # NIC "eth0" is in system_stats/nics, but NOT in bandwidth data
    data = _make_coordinator_data(nic_name="eth0", include_bandwidth=False)
    await _setup_integration(hass, data)

    tx_state = hass.states.get("sensor.test_nas_eth0_upload")
    rx_state = hass.states.get("sensor.test_nas_eth0_download")

    assert tx_state is not None, "network_tx sensor entity should exist"
    assert tx_state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE), (
        f"Expected unknown/unavailable for missing bandwidth, got tx={tx_state.state!r}"
    )

    assert rx_state is not None, "network_rx sensor entity should exist"
    assert rx_state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE), (
        f"Expected unknown/unavailable for missing bandwidth, got rx={rx_state.state!r}"
    )


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_network_sensor_nic_in_bandwidth(hass: HomeAssistant) -> None:
    """Network tx/rx sensors return correct values when NIC is present in bandwidth."""
    # bandwidth: eth0 = {tx: 1000, rx: 2000}
    data = _make_coordinator_data(nic_name="eth0", include_bandwidth=True)
    await _setup_integration(hass, data)

    tx_state = hass.states.get("sensor.test_nas_eth0_upload")
    rx_state = hass.states.get("sensor.test_nas_eth0_download")

    assert tx_state is not None
    assert tx_state.state == "1000"

    assert rx_state is not None
    assert rx_state.state == "2000"
