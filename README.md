[![License][license-shield]](LICENSE.md)

[![hacs][hacsbadge]][hacs]



# Custom component with composite Danfoss zone thermostat for Home Assistant

_Component to link danfoss zigbee TRV and thermo sensors into single entity._

_Note: Assumption is that you use Zigbee2MQTT to manage you zigbee network. It is untested with ZHA etc._

This integration combine one or many Danfoss (or OEM versions of Danfoss, like POPP) TRVs with one or many thermal sensors into single composite zone thermostat. 
Zone temperature is assumed to be an average of temperature of individual sensors. This temperature then used to feed as value of external sensor to TRVs. 
(Most likely you will need to set "radiator covered" to "true" for them, but that depends on situation).


## Installation

If you use HACS:

1. Click install.

Otherwise:

1. To use this addon, copy the `danfoss_zone_thermostat` folder into your [custom_components folder](https://developers.home-assistant.io/docs/creating_integration_file_structure/#where-home-assistant-looks-for-integrations).


## Configuration

You will need to define entities manually in the config file

Example of relevant section:
```aiignore
climate:
  - platform: danfoss_zone_thermostat
    name: MasterBedroomThermo
    sensors: [sensor.mbr_ht_temperature]
    min_temp: 14
    max_temp: 28
    valves: [climate.mbr_valve]
  - platform: danfoss_zone_thermostat
    name: LivingThermo
    sensors: [sensor.otgw_room_temperature, sensor.dining_ht_temperature]
    min_temp: 14
    max_temp: 28
    valves: [climate.living_valve1,climate.living_valve2,climate.living_valve3,climate.living_valve4]
```

In this example we create two zone thermostats. First one combines single TRV and single temperature sensor. Second one combines two temperatrure sensors and four TRVs.
Important to note, that load balancing is not integrated yet. If you need one, you can use this [blueprint](https://gist.github.com/bnapalm/9e53ba56f8b327dcc872e5da7a1db5b8), see also [discussion here](https://community.home-assistant.io/t/zigbee2mqtt-danfoss-ally-trv-room-load-balancing/468526) 

## Disclaimer
Code is unpolished. As often with such things, once I got it working for my case, I never got to implement all "would be nice to have"s :)
Initially it was developed on the base of someone's home custom assistant component, but, unfortunately, years later I don't recall what was it and can not cite original author of custom thermostat component I used. If you are the one, let me know and I will add link to you!

[hacs]: https://github.com/hacs/integration
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge
[license-shield]: https://img.shields.io/badge/license-%20%20GNU%20GPLv3%20-green?style=for-the-badge

