# oekostrom AG for Home Assistant

[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz/)

Home Assistant integration for [oekostrom AG](https://oekostrom.at/) — Austria's independent green energy provider.

Fetches data from the [mein.oekostrom.at](https://mein.oekostrom.at/) customer portal.

## Features

- **Tariff information** — current product name, energy price, base price (gross & net)
- **Account status** — supply state, smart meter flag, address, metering code
- **Billing** — installment amount, next payment date
- **Energy consumption** — 15-minute readings aggregated into Home Assistant hourly energy statistics
- **Multi-account** — supports multiple delivery points under one login
- **Auto-reauth** — re-authenticates automatically when the session expires

## Installation

### HACS (recommended)

1. Open HACS → Integrations → **Custom repositories**
2. Add this repo URL as an **Integration**
3. Search for "oekostrom AG" and install
4. Restart Home Assistant

### Manual

Copy `custom_components/oekostrom/` to your `config/custom_components/` directory and restart.

## Configuration

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **oekostrom AG**
3. Enter your `mein.oekostrom.at` email and password

Your credentials are stored locally in Home Assistant's encrypted config entry store and are only sent to `mein.oekostrom.at`.

## Sensors

Per delivery account (Strom/Gas):

| Sensor | Description |
|---|---|
| Tariff | Current product/tariff name |
| Energy price (gross) | ct/kWh including VAT |
| Energy price (net) | ct/kWh excluding VAT |
| Base price (gross) | EUR/month including VAT |
| Base price (net) | EUR/month excluding VAT |
| Account status | Active/inactive state |
| Supply status | Delivery status (e.g. "beliefert") |
| Metering code | Austrian metering point ID (Zählpunkt) |
| Installment amount | Monthly payment in EUR |
| Next installment date | Next payment due date |
| Power consumption (15min) | Latest 15-minute kWh value; long-term energy statistics are hourly totals |

See [15-minute energy consumption](./POWER_CONSUMPTION.md) for Energy dashboard setup.

## Data refresh

The integration polls the oekostrom portal once per hour. This is a reasonable default for tariff and billing data that changes infrequently.

## Privacy & Security

- Credentials are only transmitted over HTTPS to `mein.oekostrom.at`.
- No data is sent to any third-party service.
- The password is hashed before transmission (same mechanism as the web portal).
- Session tokens are held in memory only and expire automatically.

## License

MIT
