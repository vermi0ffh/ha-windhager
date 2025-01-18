# Windhager Heater

This is a custom integration for Windhager heaters to be used with Home Assistant. 

## Supported devices

| Device | Status | Notes |
|--------|:------:|-------|
| BioWIN2 | ✅ | Infowin Touch (1.0.2), API (1.0.0)  |

## Installation using HACS

1. Install [HACS](https://hacs.xyz/)
2. Add this repository as a custom repository in HACS by clicking on the three dots in the top right corner and selecting "Custom repository".
3. Enter the following as the repository URL and select "Integration" as the type:
```
https://github.com/vermi0ffh/ha-windhager
```
4. Search for "Windhager Heater" and download it.
5. Restart Home Assistant.

## Installation using manual method

1. Download the repository as a zip file from [here](https://github.com/vermi0ffh/ha-windhager/archive/refs/heads/main.zip).
2. Extract the zip file to the `custom_components` folder in your Home Assistant installation.
3. Restart Home Assistant.

## Configuration
1. Add the integration as usual.
2. Enter the host and password of your Windhager heater.
3. The integration will now be available in Home Assistant.

## Issues

If you want to debug the integration, please add the following to your `configuration.yaml` file:

```yaml
logger:
  default: warning
  logs:
    custom_components.windhager2: debug
```

This will enable debug logging for the Windhager integration. If any values are displayed as "Unknown", please check the logs for more information.

Please report any issues to the [GitHub repository](https://github.com/vermi0ffh/issues). Please include the logs and what device you are trying to integrate.

## Contributing

If you want to contribute to this project, please feel free to fork the repository and submit a pull request. Please lint and format the code using [Ruff](https://docs.astral.sh/ruff/) as recommended by the [Home Assistant development guidelines](https://developers.home-assistant.io/docs/development_guidelines).
