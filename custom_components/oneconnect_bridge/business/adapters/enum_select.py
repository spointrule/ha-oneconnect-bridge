"""Huawei enumerable-mode services: map a fixed set of modes to a HA ``select``.

Why this adapter exists
    ``get_service_adapter()`` looks adapters up by ``sid``, so every distinct
    ``serviceId`` needs an entry. Several product families expose a *fixed set of
    modes* under a service whose shape is otherwise the same: a single writable
    characteristic that carries a number, plus an ``enumList`` describing what
    each number means. Examples from the public catalogue:

    - ``lockNutrientCabin``  - fridge variable-temperature cabin (0/1/2 degree...)
    - ``iceMode``            - ice making (off / normal / rapid)
    - ``featureMode``        - fridge special modes
    - ``flexzone``           - variable-temperature cabin expressed as a *temperature*

    Writing one adapter per product is wasteful: the only thing that differs is
    the option-name-to-value table, which is configuration, not logic. This
    adapter therefore takes that table from the mapping's ``contract.values``
    and reuses the same code for every product.

    It is registered on several ``sid`` values in ``registry.py`` for that
    reason - see the alias block there.

Home Assistant mapping
    select : one ``select.`` entity. ``read_state`` turns the current option
             into the numeric value; ``apply_command`` turns the incoming value
             back into an option name and calls ``select_option``.

contract
    values : required. Option name -> numeric value, e.g.
             ``{"off": 0, "normal_ice_making": 1, "rapid_ice_making": 2}``.
             Values must be distinct; otherwise the reverse lookup is ambiguous
             and the adapter refuses to load.
             **Quote YAML keys** - ``off``/``on`` would otherwise be parsed as
             booleans and silently become strings ``"True"``/``"False"``.
    field  : which characteristic holds the value, default ``target``.
             Measured values seen in the catalogue: ``mode`` (most ``st: mode``
             services), ``target`` (``st: temperature`` ones), ``deepFreeze``
             (``featureMode``). Getting this wrong is silent - the adapter would
             look for a missing key, find nothing, and drop every command.
    scale  : numeric multiplier, default ``1``. Applies in both directions.

serviceType
    Products are inconsistent here. The same "pick one of N" semantic shows up
    as ``mode``, ``temperature`` and ``toiletSeat`` in the catalogue, so all
    three are accepted instead of forcing a rewrite of the Profile.

Boundaries
    - An incoming value that is not in ``values`` is ignored with a one-time
      warning. The adapter deliberately does **not** snap to the nearest option:
      guessing would set the cabin to a temperature the user did not ask for.
    - An ``select`` option that is not in ``values`` is not reported, likewise
      with a one-time warning.
    - One entity per service. A product with several mode services needs one
      ``sid`` each - the adapter itself is stateless and can serve many.
"""

from __future__ import annotations

import logging
import math

from ..models import ServiceRef

_LOGGER = logging.getLogger(__name__)

# (service_id, entity_id) -> set of already-warned values, to avoid log spam.
_WARNED: dict[tuple[str, str], set[object]] = {}


class EnumSelectServiceAdapter:
    service_id = "enumSelect"

    def validate_service(self, service: ServiceRef) -> None:
        if service.service_type not in _ACCEPTED_TYPES:
            raise ValueError(
                "enumSelect requires st: " + ", ".join(sorted(_ACCEPTED_TYPES))
            )
        unknown = set(dict(service.contract)) - _CONTRACT_KEYS
        if unknown:
            raise ValueError(
                "enumSelect has unsupported contract keys: "
                f"{', '.join(sorted(unknown))}"
            )
        _contract(service)

    def validate_entities(self, entity_ids: tuple[str, ...]) -> None:
        if len(entity_ids) != 1 or not entity_ids[0].startswith("select."):
            raise ValueError("enumSelect requires exactly one select entity")

    async def read_state(
        self, hass, service: ServiceRef, entity_ids: tuple[str, ...]
    ) -> dict[str, object]:
        self.validate_service(service)
        self.validate_entities(entity_ids)
        state = hass.states.get(entity_ids[0])
        if state is None or state.state in {"unknown", "unavailable"}:
            return {}
        values, field, scale = _contract(service)
        value = values.get(state.state)
        if value is None:
            _warn_once(
                (service.service_id, entity_ids[0]),
                state.state,
                "enumSelect: option %r is not in contract.values" % (state.state,),
            )
            return {}
        return {field: _wire_number(value / scale)}

    async def apply_command(
        self,
        hass,
        service: ServiceRef,
        entity_ids: tuple[str, ...],
        payload: dict[str, object],
    ) -> None:
        self.validate_service(service)
        self.validate_entities(entity_ids)
        values, field, scale = _contract(service)
        wire = _number(payload.get(field))
        if wire is None:
            return
        target = wire * scale
        option = next((name for name, value in values.items() if value == target), None)
        if option is None:
            _warn_once(
                (service.service_id, entity_ids[0]),
                wire,
                "enumSelect: value %r maps to no option" % (wire,),
            )
            return
        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": entity_ids[0], "option": option},
            blocking=True,
        )


ADAPTER = EnumSelectServiceAdapter()

# Products write the same "pick one of N" semantic under several serviceTypes.
_ACCEPTED_TYPES = frozenset({"mode", "temperature", "toiletSeat"})

_CONTRACT_KEYS = frozenset({"values", "field", "scale"})

_DEFAULT_FIELD = "target"


def _contract(service: ServiceRef) -> tuple[dict[str, float], str, float]:
    raw = service.contract_value("values")
    if not isinstance(raw, dict) or not raw:
        raise ValueError("enumSelect contract values must be a non-empty mapping")
    values: dict[str, float] = {}
    for name, value in raw.items():
        if not isinstance(name, str) or not name:
            raise ValueError(
                "enumSelect contract values keys must be non-empty text "
                "(quote on/off/yes/no in YAML so they stay text)"
            )
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("enumSelect contract values must be numeric")
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("enumSelect contract values must be finite")
        values[name] = number
    if len(set(values.values())) != len(values):
        raise ValueError(
            "enumSelect contract values must map to distinct numbers "
            "(otherwise the reverse lookup is ambiguous)"
        )

    field = service.contract_value("field", _DEFAULT_FIELD)
    if not isinstance(field, str) or not field:
        raise ValueError("enumSelect contract field must be non-empty text")

    scale = service.contract_value("scale", 1)
    if isinstance(scale, bool) or not isinstance(scale, (int, float)):
        raise ValueError("enumSelect contract scale must be numeric")
    scale = float(scale)
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("enumSelect contract scale must be positive and finite")
    return values, field, scale


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


def _wire_number(value: float) -> int | float:
    return int(value) if value.is_integer() else value


def _warn_once(key: tuple[str, str], value: object, message: str) -> None:
    seen = _WARNED.setdefault(key, set())
    if value in seen:
        return
    seen.add(value)
    _LOGGER.warning(message)
