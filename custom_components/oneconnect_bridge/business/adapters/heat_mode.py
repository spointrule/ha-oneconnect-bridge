"""Huawei ``heat`` service: a temperature setpoint plus a measured value.

Why this adapter exists
    Fridges, water heaters and some purifiers express a thermostat as
    ``st: heat`` carrying a pair of characteristics: ``target`` (RW, the setpoint)
    and ``current`` (R, the measured temperature). None of the 19 upstream
    adapters handles ``heat``, so any Profile containing it fails to load with
    ``unknown Huawei service``.

Default contract source
    prodId   : ``A403``
    Profile  : https://smarthome-drcn.dbankcdn.com/device/guide/A403/A403.json
    Service  : ``refrigeratorFloat`` / ``freezerFloat``, ``st: heat``,
               characteristics ``target`` (RW, float, degC) and
               ``current`` (R, float, degC)
    Verified : 2026-10-31 - a fridge mapped as ``A3JV`` reported the setpoint and
               the measured temperature, and ``set_temperature`` from Home
               Assistant drove the appliance (see the PR description).

Two meanings of ``heat``
    Profiles use ``heat`` both for a thermostat and for a heating *level*. This
    adapter only implements the former: ``target`` is a temperature in degrees.
    If a Profile's ``target`` is actually a level (0..5), turn ``target_field``
    off in the mapping and only report ``current``.

Home Assistant mapping
    climate : ``target``  <-> ``temperature`` / ``set_temperature``
              ``current`` <-  ``current_temperature``
    sensor  : ``current`` <-  entity state (read-only; set ``target_field: ""``)

contract
    field        : Profile characteristic name for the measured value,
                   default ``current``. ``""`` disables reporting it.
    target_field : Profile characteristic name for the setpoint, default
                   ``target``. ``""`` makes the service read-only.
    scale        : numeric multiplier, default ``1``, applied in both directions.
    At least one of ``field`` / ``target_field`` must be enabled.

Boundaries
    Exactly one entity. For ``climate`` the adapter checks ``min_temp`` /
    ``max_temp`` before calling ``set_temperature`` and drops out-of-range
    commands, so a mapping mistake cannot push the appliance to a temperature it
    does not accept.
"""

from __future__ import annotations

import math

from ..models import ServiceRef


class HeatServiceAdapter:
    service_id = "heat"

    def validate_service(self, service: ServiceRef) -> None:
        if service.service_type != "heat":
            raise ValueError("heat requires st: heat")
        unknown = set(dict(service.contract)) - {"field", "target_field", "scale"}
        if unknown:
            raise ValueError(
                f"heat has unsupported contract keys: {', '.join(sorted(unknown))}"
            )
        _measurement_contract(service)

    def validate_entities(self, entity_ids: tuple[str, ...]) -> None:
        if len(entity_ids) != 1:
            raise ValueError("heat requires exactly one sensor or climate entity")
        domain, separator, object_id = entity_ids[0].partition(".")
        if not separator or not object_id or domain not in {"sensor", "climate"}:
            raise ValueError("heat requires exactly one sensor or climate entity")

    async def read_state(
        self, hass, service: ServiceRef, entity_ids: tuple[str, ...]
    ) -> dict[str, object]:
        self.validate_service(service)
        self.validate_entities(entity_ids)
        state = hass.states.get(entity_ids[0])
        if state is None or state.state in {"unknown", "unavailable"}:
            return {}
        field, target_field, scale = _measurement_contract(service)
        domain = entity_ids[0].partition(".")[0]
        if domain == "sensor":
            if field is None:
                return {}
            value = _number(state.state)
            return {field: _wire_number(value * scale)} if value is not None else {}

        attributes = state.attributes
        result: dict[str, object] = {}
        current = _number(attributes.get("current_temperature"))
        if field is not None and current is not None:
            result[field] = _wire_number(current * scale)
        target = _number(attributes.get("temperature"))
        if target_field is not None and target is not None:
            result[target_field] = _wire_number(target * scale)
        return result

    async def apply_command(
        self,
        hass,
        service: ServiceRef,
        entity_ids: tuple[str, ...],
        payload: dict[str, object],
    ) -> None:
        self.validate_service(service)
        self.validate_entities(entity_ids)
        if entity_ids[0].partition(".")[0] != "climate":
            return
        _field, target_field, scale = _measurement_contract(service)
        if target_field is None:
            return
        wire_target = _command_number(payload.get(target_field))
        if wire_target is None:
            return
        target = wire_target / scale
        state = hass.states.get(entity_ids[0])
        if state is not None:
            low = _number(state.attributes.get("min_temp"))
            high = _number(state.attributes.get("max_temp"))
            if low is not None and target < low:
                return
            if high is not None and target > high:
                return
        step = _number(state.attributes.get("target_temp_step")) if state else None
        if step:
            target = round(target / step) * step
        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": entity_ids[0], "temperature": target},
            blocking=True,
        )


ADAPTER = HeatServiceAdapter()


def _measurement_contract(
    service: ServiceRef,
) -> tuple[str | None, str | None, float]:
    """Map HA Celsius to the Huawei field using ``scale`` in both directions."""

    field = service.contract_value("field", "current")
    target_field = service.contract_value("target_field", "target")
    scale = service.contract_value("scale", 1)
    if field == "":
        field = None
    elif not isinstance(field, str):
        raise ValueError("heat contract field must be text")
    if target_field == "":
        target_field = None
    elif not isinstance(target_field, str):
        raise ValueError("heat contract target_field must be text")
    if field is None and target_field is None:
        raise ValueError("heat contract must enable a current or target field")
    if isinstance(scale, bool) or not isinstance(scale, (int, float)):
        raise ValueError("heat contract scale must be numeric")
    try:
        scale = float(scale)
    except (OverflowError, ValueError) as error:
        raise ValueError("heat contract scale must be finite") from error
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("heat contract scale must be positive and finite")
    return field, target_field, scale


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if not isinstance(value, (int, float)):
        try:
            value = float(value)
        except (OverflowError, TypeError, ValueError):
            return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


def _command_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


def _wire_number(value: float) -> int | float:
    return int(value) if value.is_integer() else value
