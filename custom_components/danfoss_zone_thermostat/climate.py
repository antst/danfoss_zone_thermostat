"""Adds support for danfoss zone thermostat units."""
from __future__ import annotations

import asyncio
import logging
import math
from typing import Any

import voluptuous as vol
from datetime import timedelta
from homeassistant.components.climate import (
    PLATFORM_SCHEMA,
    ATTR_CURRENT_TEMPERATURE,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
    DOMAIN as CLIMATE_DOMAIN,
    SERVICE_SET_TEMPERATURE as CLIMATE_SERVICE_SET_TEMPERATURE
)
from homeassistant.components.number import (
    DOMAIN as NUMBER_DOMAIN,
    SERVICE_SET_VALUE as NUMBER_SERVICE_SET_VALUE,
    ATTR_VALUE
)

from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_TEMPERATURE,
    CONF_NAME,
    CONF_UNIQUE_ID,
    EVENT_HOMEASSISTANT_START,
    PRECISION_HALVES,
    PRECISION_TENTHS,
    PRECISION_WHOLE,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import DOMAIN as HA_DOMAIN, CoreState, HomeAssistant, callback
# from homeassistant.exceptions import ConditionError
# from homeassistant.helpers import condition
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.reload import async_setup_reload_service
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.util import dt as dt_util
from homeassistant.helpers import entity_registry

from . import DOMAIN, PLATFORMS

_LOGGER = logging.getLogger(__name__)

DEFAULT_TOLERANCE = 0.3
DEFAULT_NAME = "danfoss zone thermostat"

CONF_VALVES = "valves"
CONF_SENSORS = "sensors"
CONF_MIN_TEMP = "min_temp"
CONF_MAX_TEMP = "max_temp"
CONF_TARGET_TEMP = "target_temp"
CONF_MIN_UPDATE_INTERVAL = "min_update_interval"
CONF_MAX_UPDATE_INTERVAL = "max_update_interval"
CONF_MIN_UPDATE_TEMP_CHANGE = "min_update_temp_change"
# CONF_KEEP_ALIVE = "keep_alive"
CONF_PRECISION = "precision"
# CONF_TEMP_STEP = "target_temp_step"


PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_VALVES): vol.All(cv.ensure_list, [cv.entity_id]),
        vol.Required(CONF_SENSORS): vol.All(cv.ensure_list, [cv.entity_id]),
        vol.Optional(CONF_MAX_TEMP): vol.Coerce(float),
        vol.Optional(CONF_MIN_UPDATE_INTERVAL, default="00:05"): cv.positive_time_period,
        vol.Optional(CONF_MAX_UPDATE_INTERVAL, default="00:29"): cv.positive_time_period,
        vol.Optional(CONF_MIN_UPDATE_TEMP_CHANGE, default=0.1): vol.Coerce(float),
        vol.Optional(CONF_MIN_TEMP): vol.Coerce(float),
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_TARGET_TEMP): vol.Coerce(float),
        # vol.Optional(CONF_KEEP_ALIVE): cv.positive_time_period,
        vol.Optional(CONF_PRECISION): vol.In(
            [PRECISION_TENTHS, PRECISION_HALVES, PRECISION_WHOLE]
        ),
        # vol.Optional(CONF_TEMP_STEP): vol.In(
        #     [PRECISION_TENTHS, PRECISION_HALVES, PRECISION_WHOLE]
        # ),
        vol.Optional(CONF_UNIQUE_ID): cv.string,
    }
)


async def async_setup_platform(
        hass: HomeAssistant,
        config: ConfigType,
        async_add_entities: AddEntitiesCallback,
        discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the danfoss zone thermostat platform."""

    await async_setup_reload_service(hass, DOMAIN, PLATFORMS)

    name = config.get(CONF_NAME)
    valves_entities_id = config.get(CONF_VALVES)
    sensors_entities_id = config.get(CONF_SENSORS)
    min_temp = config.get(CONF_MIN_TEMP)
    max_temp = config.get(CONF_MAX_TEMP)
    target_temp = config.get(CONF_TARGET_TEMP)
    min_update_interval = config.get(CONF_MIN_UPDATE_INTERVAL)
    max_update_interval = config.get(CONF_MAX_UPDATE_INTERVAL)
    min_update_temp_change = config.get(CONF_MIN_UPDATE_TEMP_CHANGE)
    # keep_alive = config.get(CONF_KEEP_ALIVE)
    keep_alive = timedelta(seconds=10)
    precision = config.get(CONF_PRECISION)
    # target_temperature_step = config.get(CONF_TEMP_STEP)
    target_temperature_step = PRECISION_HALVES
    unit = hass.config.units.temperature_unit
    unique_id = config.get(CONF_UNIQUE_ID)

    async_add_entities(
        [
            DanfossZoneThermostat(
                name,
                valves_entities_id,
                sensors_entities_id,
                min_temp,
                max_temp,
                target_temp,
                min_update_interval,
                max_update_interval,
                min_update_temp_change,
                keep_alive,
                precision,
                target_temperature_step,
                unit,
                unique_id,
            )
        ]
    )


class DanfossZoneThermostat(ClimateEntity, RestoreEntity):
    """Representation of a danfoss zone thermostat device."""

    _attr_should_poll = False

    def __init__(
            self,
            name,
            valves_entities_id,
            sensors_entities_id,
            min_temp,
            max_temp,
            target_temp,
            min_update_interval,
            max_update_interval,
            min_update_temp_change,
            keep_alive,
            precision,
            target_temperature_step,
            unit,
            unique_id,
    ):
        """Initialize the thermostat."""
        self._attr_name = name
        self.valves_entities_id = valves_entities_id
        self.sensors_entities_id = sensors_entities_id
        self.min_update_interval = int(cv.positive_time_period(min_update_interval).total_seconds())
        self.max_update_interval = int(cv.positive_time_period(max_update_interval).total_seconds())
        self.min_update_temp_change = int(float(min_update_temp_change) * 100)
        self._keep_alive = keep_alive
        self._hvac_mode = HVACMode.HEAT
        self._saved_target_temp = target_temp or None
        self._temp_precision = precision
        self._temp_target_temperature_step = target_temperature_step
        self._attr_hvac_modes = [HVACMode.HEAT]
        self._active = False
        self._cur_temp = None
        self._temp_lock = asyncio.Lock()
        self._min_temp = min_temp
        self._max_temp = max_temp
        self._target_temp = target_temp
        self._attr_temperature_unit = unit
        self._attr_unique_id = unique_id
        self._attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
        self._action = HVACAction.OFF
        self._last_fired = dict()
        self._ext_entities = dict()
        _LOGGER.warning("Update constrains for %s : %s %s %s", self.name, self.min_update_interval,
                        self.max_update_interval, self.min_update_temp_change)

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added."""
        await super().async_added_to_hass()

        # Add listener
        for sensor in self.sensors_entities_id:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, sensor, self._async_sensor_changed
                )
            )

        for valve in self.valves_entities_id:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, valve, self._async_valve_changed
                )
            )

        for valve in self.valves_entities_id:
            self._last_fired[valve] = 0
            registry = entity_registry.async_get(self.hass)
            r1 = registry.async_get(valve)
            # _LOGGER.warning("rX: %s", r1)
            entities = entity_registry.async_entries_for_device(registry, r1.device_id)
            for ent in entities:
                if ent.unique_id.find("external_measured_room_sensor") >= 0:
                    self._ext_entities[valve] = ent.entity_id
                    break

        if self._keep_alive:
            self.async_on_remove(
                async_track_time_interval(
                    self.hass, self._async_transfer_temperature, self._keep_alive
                )
            )

        @callback
        def _async_startup(*_):
            """Init on startup."""
            cur_temp = self._get_average_sensor_state()
            # _LOGGER.warning("boot %f", cur_temp)
            if not (math.isnan(cur_temp) or math.isinf(cur_temp)):
                self._async_update_temp(cur_temp)
                self.async_write_ha_state()

        if self.hass.state == CoreState.running:
            _async_startup()
        else:
            self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_START, _async_startup)

        # Check If we have an old state
        if (old_state := await self.async_get_last_state()) is not None:
            # If we have no initial temperature, restore
            if self._target_temp is None:
                # If we have a previously saved temperature
                if old_state.attributes.get(ATTR_TEMPERATURE) is None:
                    self._target_temp = self.min_temp
                    _LOGGER.warning(
                        "Undefined target temperature, falling back to %s",
                        self._target_temp,
                    )
                else:
                    self._target_temp = float(old_state.attributes[ATTR_TEMPERATURE])
            if self._cur_temp is None:
                #_LOGGER.warning("old state %s", old_state)
                # If we have a previously saved temperature
                if old_state.attributes.get(ATTR_CURRENT_TEMPERATURE) is not None:
                    self._cur_temp = float(old_state.attributes.get(ATTR_CURRENT_TEMPERATURE))
        else:
            # No previous state, try and restore defaults
            if self._target_temp is None:
                self._target_temp = self.min_temp
            _LOGGER.warning(
                "No previously saved temperature, setting to %s", self._target_temp
            )

        # Set default state to off
        if not self._hvac_mode:
            self._hvac_mode = HVACMode.HEAT

    @property
    def precision(self):
        """Return the precision of the system."""
        if self._temp_precision is not None:
            return self._temp_precision
        return super().precision

    @property
    def target_temperature_step(self):
        """Return the supported step of target temperature."""
        if self._temp_target_temperature_step is not None:
            return self._temp_target_temperature_step
        # if a target_temperature_step is not defined, fallback to equal the precision
        return self.precision

    @property
    def current_temperature(self):
        """Return the sensor temperature."""
        return self._cur_temp

    @property
    def hvac_mode(self):
        """Return current operation."""
        return self._hvac_mode

    @property
    def hvac_action(self) -> HVACAction | None:
        """Return the current running hvac operation if supported.

        Need to be one of CURRENT_HVAC_*.
        """
        # if not self._is_device_active:
        #     return HVACAction.IDLE
        return self._action

    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        return self._target_temp

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set hvac mode."""
        if hvac_mode == HVACMode.HEAT:
            self._hvac_mode = HVACMode.HEAT
            await self._async_control_heating(force=True)
        else:
            _LOGGER.error("Unrecognized hvac mode: %s", hvac_mode)
            return
        # Ensure we update the current operation after changing the mode
        self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is None:
            return
        # _LOGGER.warning("Set target temp to %s", temperature)
        self._target_temp = temperature
        for valve in self.valves_entities_id:
            await self.hass.services.async_call(
                CLIMATE_DOMAIN, CLIMATE_SERVICE_SET_TEMPERATURE, {
                    ATTR_ENTITY_ID: valve,
                    ATTR_TEMPERATURE: temperature
                }, blocking=True)
        self.async_write_ha_state()

    @property
    def min_temp(self):
        """Return the minimum temperature."""
        if self._min_temp is not None:
            return self._min_temp
        return super().min_temp

    @property
    def max_temp(self):
        """Return the maximum temperature."""
        if self._max_temp is not None:
            return self._max_temp

        # Get default temp from super class
        return super().max_temp

    def _get_average_sensor_state(self) -> float:
        new_temp = 0.0
        num_vals = 0
        for sensor in self.sensors_entities_id:

            # _LOGGER.warning("sens %s", sensor)
            state = self.hass.states.get(sensor)
            # _LOGGER.warning("sens_state %s", state)
            if not (state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN)):
                cur_temp = float(state.state)
                # _LOGGER.warning("Cur temp %f", cur_temp)
                if not (math.isnan(cur_temp) or math.isinf(cur_temp)):
                    new_temp += cur_temp
                    num_vals += 1
        # _LOGGER.warning("sens_numvals %d, %f", num_vals, float(num_vals))
        if num_vals > 0:
            new_temp /= float(num_vals)
        else:
            new_temp = float("nan")
        # _LOGGER.warning("sens_newtemp %f", new_temp)
        # if math.isnan(new_temp) or math.isinf(new_temp):
        #     raise ValueError(f"Sensor has illegal state {new_temp}")
        return new_temp

    async def _async_sensor_changed(self, event):
        """Handle temperature changes."""
        new_state = event.data.get("new_state")
        if new_state is None or new_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return
        cur_temp = self._get_average_sensor_state()

        self._async_update_temp(cur_temp)
        self.async_write_ha_state()
        await self._async_transfer_temperature()

    @callback
    def _async_valve_changed(self, event):
        """Handle heater switch state changes."""
        new_state = event.data.get("new_state")
        if new_state is None:
            return
        target_temp = 0.0
        num_vals = 0
        hvac_action = HVACAction.OFF
        for valve in self.valves_entities_id:
            # _LOGGER.warning("valve %s", valve)
            state = self.hass.states.get(valve)
            # _LOGGER.warning("valve_state %s", state)
            if not (state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN)):
                state_action = state.attributes.get("hvac_action")
                if state_action == HVACAction.HEATING:
                    hvac_action = HVACAction.HEATING

                state_temp = state.attributes.get("temperature")
                # _LOGGER.warning("valve_target %s", state_temp)
                if not (math.isnan(state_temp) or math.isinf(state_temp)):
                    target_temp += state_temp
                    num_vals += 1
        if num_vals > 0:
            self._target_temp = target_temp / float(num_vals)

        self._action = hvac_action
        self.async_write_ha_state()

    @callback
    def _async_update_temp(self, cur_temp):
        """Update thermostat with the latest state from sensor."""
        try:
            if math.isnan(cur_temp) or math.isinf(cur_temp):
                raise ValueError(f"Sensor has illegal state {cur_temp}")
            self._cur_temp = cur_temp
            self.state_attributes[ATTR_CURRENT_TEMPERATURE] = cur_temp

        except ValueError as ex:
            _LOGGER.error("Unable to update from sensor: %s", ex)

    async def _async_transfer_temperature(self, time=None):
        # _LOGGER.warning(
        #     "Call to temp.transfer for %s with time=%s",self.name, time)
        async with self._temp_lock:
            now = int(dt_util.utcnow().timestamp())
            if self._cur_temp is None:
                return
            ext_temp = int(round(self._cur_temp * 100.0))
            for valve in self.valves_entities_id:
                state = self.hass.states.get(self._ext_entities[valve])
                if not (state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN)):
                    current_ext_temp = float(state.state)
                    delta_t = now - self._last_fired[valve]
                    # _LOGGER.warning("Delta_t for %s is %s (%s,%s)", self.name, delta_t,self.min_update_interval,self.max_update_interval)

                    if (delta_t >= self.min_update_interval and
                        abs(ext_temp - current_ext_temp) >= self.min_update_temp_change) or \
                            (delta_t >= self.max_update_interval):
                        _LOGGER.warning(
                            "Set external temperature for %s to %s (before %s), after dt %s ",
                            self._ext_entities[valve], ext_temp, current_ext_temp, delta_t)
                        await self.hass.services.async_call(
                            NUMBER_DOMAIN, NUMBER_SERVICE_SET_VALUE, {
                                ATTR_ENTITY_ID: self._ext_entities[valve],
                                ATTR_VALUE: ext_temp
                            }, blocking=True)
                        self._last_fired[valve] = now

    @property
    def _is_device_active(self):
        """If the toggleable device is currently active."""
        # if not self.hass.states.get(self.valves_entities_id):
        #     return None

        return self.hass.states.is_state(self.valves_entities_id, STATE_ON)
