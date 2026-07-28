# BTicino C100X for Home Assistant

A native Home Assistant integration for BTicino Classe 100X door-entry units
running firmware 1.x. It uses Legrand's Door Entry cloud topology and the
Classe 100X SIP channel for momentary electric-strike releases and real-time
ringing, without modifying the intercom firmware.

## Beta scope

- Pulse the door release at any time from Home Assistant
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
locked. The **Release door** button only pulses the electric strike for its
configured interval; it does not represent a stateful smart lock or report
whether the physical door is open.

## Attribution

Protocol behavior was independently implemented from the Classe 100X API and
the vendor-signed Door Entry CLASSE100X Android application.
