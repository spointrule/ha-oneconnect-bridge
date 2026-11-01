"""Explicit registry of trusted Huawei service adapters."""

from __future__ import annotations

from .action import ADAPTER as ACTION
from .api import ServiceAdapter
from .alarm import ADAPTER as ALARM
from .air_detector import ADAPTER as AIR_DETECTOR
from .brightness import ADAPTER as BRIGHTNESS
from .cct import ADAPTER as CCT
from .cleaner_robot import ADAPTER as CLEANER_ROBOT
from .colour import ADAPTER as COLOUR
from .enum_select import ADAPTER as ENUM_SELECT
from .filter_element import ADAPTER as FILTER_ELEMENT
from .heat_mode import ADAPTER as HEAT_MODE
from .electric import ADAPTER as ELECTRIC
from .gas_sensor import ADAPTER as GAS_SENSOR
from .fan import ADAPTER as FAN
from .hcho import ADAPTER as HCHO
from .humidity import ADAPTER as HUMIDITY
from .mode import ADAPTER as MODE
from .motor import ADAPTER as MOTOR
from .open_level import ADAPTER as OPEN_LEVEL
from .opener import ADAPTER as OPENER
from .status import ADAPTER as STATUS
from .switch import ADAPTER as SWITCH
from .temperature import ADAPTER as TEMPERATURE


_SERVICE_ADAPTERS: dict[str, ServiceAdapter] = {
    adapter.service_id: adapter
    for adapter in (
        SWITCH,
        BRIGHTNESS,
        CCT,
        COLOUR,
        ELECTRIC,
        TEMPERATURE,
        HUMIDITY,
        AIR_DETECTOR,
        MOTOR,
        OPEN_LEVEL,
        OPENER,
        HCHO,
        ALARM,
        GAS_SENSOR,
        MODE,
        FAN,
        CLEANER_ROBOT,
        STATUS,
        ACTION,
        ENUM_SELECT,
        FILTER_ELEMENT,
        HEAT_MODE,
    )
}
for _service_id in ("switch1", "switch2", "switch3"):
    _SERVICE_ADAPTERS[_service_id] = SWITCH
_SERVICE_ADAPTERS["leftAction"] = ACTION

# A thermostat is expressed as ``st: heat`` on 96 products in the catalogue
# (fridge compartments, water heaters, purifier outlet temperature), and the
# characteristic is named per product (``refrigeratorFloat``, ``freezerFloat``,
# ...). They all carry ``target`` / ``current`` pairs, so they share one adapter.
for _service_id in ("refrigeratorFloat", "freezerFloat", "refrigerator", "freezer"):
    _SERVICE_ADAPTERS[_service_id] = HEAT_MODE

# A consumable filter is exposed under its own ``sid`` per filter slot, so a
# product with two filters publishes ``filterElement1`` and ``filterElement2``.
# The numbered variants behave identically; each ``sid`` is still registered
# exactly once and keeps its Profile spelling.
for _service_id in (
    "filterElement",
    "filterElement1",
    "filterElement2",
    "filterElement3",
    "filterElement4",
    "commonFilterElement1",
):
    _SERVICE_ADAPTERS[_service_id] = FILTER_ELEMENT

# "Pick one of N" modes. The serviceType is written inconsistently across the
# catalogue (``mode``, ``temperature``, ``toiletSeat``) and the characteristic
# is named per product, but the shape is always "a numeric field plus an
# enumList". The difference between products is the option-to-number table,
# which belongs in the mapping's ``contract.values``, not in Python. One adapter
# therefore serves every such service; the sids below are the ones observed.
for _service_id in (
    "lockNutrientCabin",
    "aiVersatileCabin",
    "aiNutrientCabin",
    "AttemperMode",
    "transformingSetting",
    "flexiTempCabin",
    "flexzone",
    "iceMode",
):
    _SERVICE_ADAPTERS[_service_id] = ENUM_SELECT


def get_service_adapter(service_id: str) -> ServiceAdapter:
    try:
        return _SERVICE_ADAPTERS[service_id]
    except KeyError as error:
        raise ValueError(f"unknown Huawei service: {service_id}") from error
