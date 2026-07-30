# BTicino C100X for Home Assistant

A native Home Assistant integration for BTicino Classe 100X door-entry units
running firmware 1.x. It uses Legrand's Door Entry cloud topology and the
Classe 100X SIP channel for momentary electric-strike releases and real-time
ringing, without modifying the intercom firmware.

## Features

- Start an on-demand Classe 100X monitoring session without changing firmware
- Receive live video and intercom audio through a standard Home Assistant camera
- Use the bundled `bticino-c100x-card` in browsers and Companion App WebViews
- Keep the microphone disabled until the card's explicit microphone action
- Share one SIP media session between multiple viewers and clean it up automatically
- Pulse any vendor-visible door release at any time from Home Assistant
- Receive real-time doorbell events
- Use doorbell events in automations and Companion App notifications
- Keep the official Door Entry app operational through a separate SIP account
- Expose SIP registration and certificate-expiry diagnostics

Staircase lighting is intentionally not included. There is no architecture-specific
helper: the integration uses the FFmpeg installation supplied with Home Assistant
OS and Home Assistant Container.

## Installation

1. In HACS, open **Integrations**, then **Custom repositories**.
2. Add `https://github.com/alpichlabs/ha-bticino-c100x` as an integration.
3. Install **BTicino C100X** and restart Home Assistant.
4. Add the integration from **Settings → Devices & services**.

The integration uses Home Assistant's FFmpeg system integration for received
H.264 video. SIP signaling, SDES-SRTP audio and microphone mute state remain
inside the integration; no control or media service is exposed externally. In
Lovelace storage mode the bundled card resource is
registered automatically; add a **BTicino C100X Intercom** card and select the
camera, Start, End and Release entities. The regular camera entity is also usable
with Home Assistant's native WebRTC player.

RTP and RTCP endpoints are discovered through the same Linphone STUN service
used by the vendor app. The integration advertises the mapped endpoints and
opens symmetric UDP paths before media reception, so Home Assistant Container
deployments do not expose container-private addresses in the monitoring offer.
The browser-facing WebRTC peer uses STUN as well, allowing the camera player to
reach an integration running on a Docker bridge.

```yaml
type: custom:bticino-c100x-card
camera_entity: camera.front_door
start_entity: button.start_monitoring
end_entity: button.end_session
release_entity: button.release_door
```

The card normally resolves the integration entry from the camera entity. An
explicit `entry_id` may be supplied for older frontend versions.

Credentials are entered only in Home Assistant. They must never be included in
issues or diagnostic logs.

Opening the live camera or pressing **Start monitoring** is an explicit user
action and places one monitoring call to the external unit. Dashboard snapshot
refreshes only read the last cached JPEG and never place a call. **End session**
hangs up immediately; otherwise the call ends ten seconds after the final viewer
disconnects.

## Safety

This is an unofficial integration. Test the beta with the entrance mechanically
locked. The **Release door** button only pulses the electric strike for its
configured interval; it does not represent a stateful smart lock or report
whether the physical door is open.

## Attribution

Protocol behavior was independently implemented from the Classe 100X API and
the vendor-signed Door Entry CLASSE100X Android application.

The vendor app uses Linphone, while this interoperability implementation uses
Home Assistant's existing [FFmpeg](https://ffmpeg.org/) installation for video
decoding and the MIT/BSD-licensed `aiortc`/`pylibsrtp` Python packages for local
WebRTC and SRTP handling. This repository remains MIT-licensed and does not
redistribute FFmpeg or Linphone binaries.

Related community work includes the MIT-licensed
[`adaofeliz/bticino-door-entry-v1`](https://github.com/adaofeliz/bticino-door-entry-v1),
which implements an alternative Legrand cloud REST approach for Classe 100X
firmware v1. Its implementation was consulted for protocol comparison; no code
was copied into this integration.

The independently derived [Classe 100X protocol reference](docs/classe-100x-protocol.md)
documents the app and cloud behavior used by this integration, including
evidence levels and remaining unknowns.
