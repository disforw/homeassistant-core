"""Tests for QNAP update platform."""

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
    STATE_OFF,
    STATE_ON,
)
from homeassistant.core import HomeAssistant

from tests.common import MockConfigEntry

TEST_NAS_NAME = "Test NAS"
TEST_SERIAL = "QX1234567"
INSTALLED_VERSION = "5.1.0.2548"

ENTRY_DATA = {
    CONF_HOST: "1.2.3.4",
    CONF_USERNAME: "admin",
    CONF_PASSWORD: "password",
    CONF_SSL: DEFAULT_SSL,
    CONF_VERIFY_SSL: DEFAULT_VERIFY_SSL,
    CONF_PORT: DEFAULT_PORT,
    CONF_TIMEOUT: DEFAULT_TIMEOUT,
}


def _make_system_stats() -> dict[str, Any]:
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
            "version": INSTALLED_VERSION,
            "build": "20230101",
            "patch": "0",
        },
        "nics": {
            "eth0": {
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
    firmware_update: str | None = None,
) -> dict[str, Any]:
    """Build a minimal coordinator data dict for update entity testing."""
    return {
        "system_stats": _make_system_stats(),
        "system_health": "OK",
        "smart_drive_health": {
            "HDD 1": {
                "health": "good",
                "temp_c": 35,
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
        "bandwidth": {"eth0": {"tx": 1000, "rx": 2000}},
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
# Update entity — no update available
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_firmware_update_entity_no_update(hass: HomeAssistant) -> None:
    """Update entity state is OFF when get_firmware_update() returns None."""
    data = _make_coordinator_data(firmware_update=None)
    await _setup_integration(hass, data)

    state = hass.states.get("update.test_nas_firmware_update")
    assert state is not None
    assert state.state == STATE_OFF


# ---------------------------------------------------------------------------
# Update entity — update available
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_firmware_update_entity_update_available(hass: HomeAssistant) -> None:
    """Update entity state is ON when a newer firmware version is available."""
    latest = "5.2.0.1234 Build 20240101"
    data = _make_coordinator_data(firmware_update=latest)
    await _setup_integration(hass, data)

    state = hass.states.get("update.test_nas_firmware_update")
    assert state is not None
    assert state.state == STATE_ON
    assert state.attributes["installed_version"] == INSTALLED_VERSION
    assert state.attributes["latest_version"] == latest


# ---------------------------------------------------------------------------
# Update entity — installed_version reflects coordinator firmware version
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_firmware_update_entity_installed_version(hass: HomeAssistant) -> None:
    """installed_version attribute reflects the firmware version from system_stats."""
    data = _make_coordinator_data(firmware_update=None)
    await _setup_integration(hass, data)

    state = hass.states.get("update.test_nas_firmware_update")
    assert state is not None
    assert state.attributes["installed_version"] == INSTALLED_VERSION
