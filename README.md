# BTicino C100X for Home Assistant

A native Home Assistant integration for BTicino Classe 100X door-entry units
running firmware 1.x. It uses Legrand cloud authentication and the door-entry
SIP service without modifying the intercom firmware.

## Beta scope

- Unlock the door at any time from Home Assistant
- Receive real-time doorbell events
- Use doorbell events in automations and Companion App notifications
- Keep the official Door Entry app operational through a separate SIP account
- Expose SIP registration and certificate-expiry diagnostics

Video, two-way audio, HomeKit and staircase lighting are not included.

## Installation

1. In HACS, open **Integrations**, then **Custom repositories**.
2. Add `https://github.com/alpichlabs/ha-bticino-c100x` as an integration.
3. Install **BTicino C100X** and restart Home Assistant.
4. Add the integration from **Settings → Devices & services**.

Credentials are entered only in Home Assistant. They must never be included in
issues or diagnostic logs.

## Safety

This is an unofficial integration. Test the beta with the entrance mechanically
locked. Home Assistant reports an unlock as successful only after the SIP server
returns a successful response.

## Attribution

Protocol behavior was independently implemented with reference to the MIT
licensed projects `adaofeliz/bticino-door-entry-v1` and
`s-dimaio/BTicinoDoorEntry`.

