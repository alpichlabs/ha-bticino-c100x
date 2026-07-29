# BTicino Classe 100X protocol reference

This document describes the interfaces used by the Android **Door Entry for Classe 100X** application. It is an independent interoperability note, not official Legrand documentation. It targets Classe 100X installations using the 1.x firmware/cloud generation; do not assume that it applies to Classe 300EOS, Home + Security, or firmware 2.x.

## Evidence and scope

The primary artifact was Android application 1.8.4 (package `com.legrandgroup.c100x`, version code 108):

- APK SHA-256: `b5d5340d18e8eeff34a33cca9a994c1b78398e52ab6be5332764482e4e472498`
- complete XAPK SHA-256: `3be83095c381175f2d4d96b6e9c0c494e09df17ac4cf3aff4a5978f977e45da7`
- arm64 split SHA-256: `47ff367d790f10afcd9e9c32874e3be0a58f40366172221bd2810a84e641fa6b`
- signing-certificate SHA-256: `93d0112925ad92f872cf20cf3397f096e923336e5752435e3ed6cd5c93f8f021`
- minimum/target Android API: 23/35

The base APK and every inspected split report package `com.legrandgroup.c100x`, version code 108, and the same signing certificate. The arm64 split contains one native library, `liblinphone.so`. This identity chain is important: native conclusions below come from the Classe 100X app bundle, not from a Classe 300X project or a generic Linphone binary.

The app was inspected statically. No certificate, token, password, personal identifier, or live traffic is published here. Decompiled names can be incomplete because the release is obfuscated.

Evidence labels used below:

- **Confirmed**: directly represented by application bytecode or data models.
- **Observed**: seen against the test installation, without publishing its identifiers.
- **Inferred**: strongly implied by code but not exercised end to end.
- **Unknown**: the app does not provide enough evidence to state the behavior safely.

### Applicability rule

A behavior is treated as Classe 100X evidence only when at least one of these conditions holds:

1. it is reachable from package `com.legrandgroup.c100x` in the vendor-signed 1.8.4 app;
2. it is returned by the live account/topology used by that app and agrees with its model mapping; or
3. it is implemented by the native Linphone split shipped with that same signed app.

Names found only in Classe 300X projects, Home + Security/Netatmo integrations, or generic Linphone documentation are comparison material, not proof of Classe 100X behavior. `netatmo_cam` is an explicit topology type handled by the Classe 100X app for an auxiliary camera; its name does not move the intercom itself onto the newer Home + Security API generation.

### Firmware 1.5.8 compatibility

The Classe 100X app performs an explicit firmware check during full alignment. Its recovered predicate splits the gateway firmware string into three integers and requires major `>= 1`, minor `>= 5`, and patch `>= 8`. Firmware `1.5.8` therefore passes the exact app-side gate (**Confirmed**). The app also labels the locally discovered gateway model `bs-classe100x` and requires commissioning product code `99`.

This establishes scope for the installation under test: the cloud/SIP procedures below are reached by the current vendor-signed Classe 100X app for firmware 1.5.8. No firmware replacement, shell access to the intercom, or C300X controller installation is part of this protocol.

## Architecture

The app does not expose a single REST “door entry API.” It combines four systems:

1. Azure AD B2C authenticates the Legrand account and issues OAuth tokens.
2. Legrand HTTPS APIs return plants, topology modules, SIP accounts, push subscriptions, firmware information, and client certificates.
3. A mutually authenticated SIP-over-TLS session handles registration, calls, early video, audio, and JSON-RPC commands sent as SIP chat messages.
4. Firebase Cloud Messaging wakes or refreshes SIP registration when an incoming call is pending.

The gateway module ID, topology actuator module ID, SIP account, and phone/app client ID are different identifiers. They must not be substituted for one another.

### Why the Classe 100X app contains Netatmo camera code

`netatmo_cam` is an optional camera type inside the Classe 100X topology. The app sends `netatmo.getStatus`, `netatmo.getCameras`, `netatmo.setStatus`, `netatmo.setLogin`, and `netatmo.setPresenceHome` JSON-RPC bodies through Device Management endpoints under `modules/<module-id>/commands/{getCameras,getStatus,setStatus,setLogin,setPresence}`. Returned cameras are then exposed as camera-only SIP viewing targets using `TVCC=1`.

That is an accessory bridge implemented by the Classe 100X gateway/app. It is not the strike path, does not change the gateway type from `bs-classe100x`, and is not evidence that this integration should use the Home + Security/Netatmo firmware-2.x authentication model. No Netatmo procedure is needed for the installation under test unless such an auxiliary camera is actually configured.

## Production service roots

These production roots are **Confirmed**:

| Purpose | Root |
|---|---|
| Legrand API gateway | `https://api.developer.legrand.com/` |
| Service catalogue v3 | `servicecatalog/api/v3.0/` |
| Device management v2 | `devicemanagement/api/v2.0/` |
| Certificate authority v1 | `certificate/api/v1.0/ca/information/` |
| Door Entry SIP provisioning v1 | `vde/sip/v1.0/` |
| Door Entry push v1 | `vde/push/v1.0/devices/` |
| User service | `users/api/v1.0/users`, plus v2/v3 variants |
| Terms and conditions | `termsandconditions/api/V2.0` |
| Remote SIP proxy | `vdesip.bs.iotleg.com` |
| Per-gateway SIP domain | `<gateway-module-id>.bs.iotleg.com` |

The APK also contains QA/pre-production endpoints. They are deliberately omitted: they are irrelevant to a production integration and are not a supported public environment.

## OAuth authentication

The production app uses Azure AD B2C authorization-code authentication (**Confirmed**):

- tenant: `EliotClouduamprd.onmicrosoft.com`
- sign-in policy: `B2C_1_DoorEliot-C100X-SignUporSignIn`
- password-reset policy: `B2C_1_DoorEliot-C100X-password`
- profile policy: `B2C_1_DoorEliot-C100X-profile`
- redirect URI: `com.legrandgroup.c100x://oauth2redirect`
- scope: `https://EliotClouduamprd.onmicrosoft.com/security/access.full offline_access` (the interactive flow also requests OpenID)

Authorization and token URLs have the normal B2C form:

```text
GET  https://eliotclouduamprd.b2clogin.com/EliotClouduamprd.onmicrosoft.com/oauth2/v2.0/authorize?p=<policy>
POST https://eliotclouduamprd.b2clogin.com/EliotClouduamprd.onmicrosoft.com/oauth2/v2.0/token?p=<policy>
```

The application ID and API subscription key are identifiers embedded in the distributable app, not user secrets. A separate application-level client credential is also embedded by the vendor; this document does not reproduce it because third-party clients do not need it for the normal user authorization-code/refresh-token path.

Access tokens are passed as `Authorization: Bearer <access-token>`. Some certificate and user operations additionally pass a token in `UserToken`. OAuth refresh tokens are used to renew access without repeating the interactive sign-in.

The recovered authorization library builds a conventional `response_type=code` request with client ID, redirect URI, and configured scopes, then exchanges the returned code with the redirect URI and public client ID. No `code_challenge` or `code_verifier` string or setter was found anywhere in the APK, so PKCE is not evidenced in app 1.8.4. The login WebView enables JavaScript, disables its cache, and removes previous cookies. Credentials are persisted under the logical key `azureb2c`; refresh uses the B2C token endpoint and public-client authentication without a client secret.

## Common HTTPS headers

Most JSON API calls use (**Confirmed**):

```http
Authorization: Bearer <user-access-token>
Ocp-Apim-Subscription-Key: <Door Entry application subscription key>
Content-Type: application/json
```

Certificate and selected user calls add:

```http
UserToken: <user-access-token or application-token, according to the call path>
```

The HTTP API manager contains a sanitizer for `sipPassword`, `access_token`, `cert`, client secrets, API keys, and passwords. Other recovered authentication code nevertheless includes debug statements that interpolate access and refresh tokens directly. That is a vendor implementation weakness, not behavior to reproduce: this integration must never emit either token at any log level.

## HTTPS endpoint catalogue

Volley numeric methods in the APK map to GET=0, POST=1, PUT=2, DELETE=3, and PATCH=7. The following endpoint construction and response classes are **Confirmed**. Bodies marked “model” are serialized model objects; fields not exercised by this integration may be optional server-side.

### Topology, plants, and users

| Method | Path relative to API gateway | Request | Response |
|---|---|---|---|
| GET | `servicecatalog/api/v3.0/plants/{plantId}` | — | `Plant` |
| POST | `servicecatalog/api/v3.0/plants` | `Plant` | `Plant` |
| GET | `servicecatalog/api/v3.0/modules` | — | `Module[]` |
| GET | `servicecatalog/api/v3.0/modules/{moduleId}` | — | `Module` |
| PATCH | `servicecatalog/api/v3.0/modules/{moduleId}` | partial module JSON | `Module` |
| POST | `servicecatalog/api/v3.0/plants/{plantId}/delegatedusers/{userId}/` | — | string |
| DELETE | same delegated-user path | — | string |
| POST | `servicecatalog/api/v3.0/plants/{plantId}/owner/{userId}/` | `Password` model | string |
| DELETE | `servicecatalog/api/v3.0/plants/{plantId}?forceDelete=true` | — | string |
| DELETE | `users/api/v1.0/users` | —; extra `UserToken` | string |

The app’s `Plant` model contains `id`, `name`, `country`, `type`, `ownerId`, and `ownerEmail`, plus local database indices. Its `Module` model contains `id`, `plantId`, `gatewayId`, device/model/type, firmware/hardware versions, name, serial/MAC/IP, owner information, activation date, allowed/invited users, and arbitrary `{key,value}` tags.

Actuators are topology modules. A lock/strike module ID is not the gateway ID. The app dispatches actions according to component identifiers (CIDs):

| CID | Meaning in app | JSON-RPC action |
|---:|---|---|
| `10060` | `Lock` topology device and session/default lock action | `lock.setStatus` |
| `3008` | legacy lock-like database entry accepted by the action dispatcher | `lock.setStatus` |
| `2009` | staircase light | `light.setStatus` |

During cloud alignment, the app maps `deviceType` values to its local database as follows: `Lock` → CID `10060`, `SecureLock` → `10070`, `Staircase` → `2009`, `EU` → `10050`, `netatmo_cam` → `10061`, and `IU` → an intercom type. A separate legacy database query selects CIDs `3008` and `2009`, while the action dispatcher accepts both `10060` and `3008` for `lock.setStatus`. It does not accept `10070` in that dispatcher.

Most importantly, the official app sets both the local `deviceAddr` and the JSON-RPC receiver parameter from the cloud module's `id`. A `PrivateAddress` tag is parsed only for `buttonId` and `visible` UI metadata in this flow. Values such as `21` or `22` nested in that tag are not used as the receiver of `lock.setStatus`. Each current cloud `Lock` module must therefore remain a distinct selectable strike; only modules absent from the latest topology are stale.

### SIP accounts

| Method | Path | Request | Response |
|---|---|---|---|
| GET | `vde/sip/v1.0/devices/{gatewayId}/sipaccounts` | — | `SipUser[]` |
| POST | `vde/sip/v1.0/devices/{gatewayId}/sipaccount` | SIP client registration model | `SipUser` |
| DELETE | `vde/sip/v1.0/devices/{gatewayId}/sipaccount/{sipAccountId}` | — | string |
| DELETE | `vde/sip/v1.0/devices/{gatewayId}/sipaccount/users` | — | string |

`SipUser` fields are `clientId`, `clientName`, `deviceId`, `plantId`, `sipId`, `sipPassword`, `sipUri`, `userOid`, and `username`. `sipPassword` is secret. The SIP URI identifies the app client and normally ends in `@<gatewayId>.bs.iotleg.com`.

### Client certificates

| Method | Path | Request | Response |
|---|---|---|---|
| GET | `certificate/api/v1.0/ca/information/CACerts` | —; extra `UserToken` | `{ "chain": ... }` |
| POST | `certificate/api/v1.0/ca/information/clientCerts` | certificate request | `{ "cert": ... }` |

Certificate creation in the official app is **Confirmed** as follows:

1. Generate an EC key pair on curve `prime256v1`/P-256 locally.
2. Keep the private key local; only a PKCS#10 CSR is uploaded.
3. Sign the CSR with SHA-256 with ECDSA.
4. Use the subject `EMAILADDRESS=<account-email>, C=FR, ST=France, L=Paris, O=LEGRAND, OU=C100X, CN=<client-id>`.
5. Add a URI subject alternative name `sip:<sip-uri>`.
6. Convert the PEM CSR to DER and Base64-encode it for JSON.
7. Submit it with template `sipuser` and sender `{system: "information", addressType: "addressLocation", plant: <Plant>}`.
8. Store the returned client certificate and CA chain with the private key for SIP TLS.

The certificate calls first obtain a separate application token through the app's embedded client-credentials flow. The official request helper `u(userToken, bearerToken, key)` places the **application token** in `Authorization: Bearer ...` and the **user access token** in `UserToken`. This ordering is confirmed by both `U2.h1` call sites and `R2.a.u`; treating both headers as the same token, or reversing them, is not an exact reproduction of the official app.

The official app checks certificate validity 30 days into the future (`now + 2,592,000,000 ms`). If that check fails, it deletes the stored key/certificate material so the alignment/provisioning flow can create a new set. Consequently, a long-running integration must renew before this 30-day window, not merely on the `notAfter` date.

### Push notifications

| Method | Path | Request | Response |
|---|---|---|---|
| GET | `vde/push/v1.0/devices/{gatewayId}/subscription` | — | `PushNotification[]` |
| POST | same path | `PushNotification` | `PushNotification` |
| DELETE | `vde/push/v1.0/devices/{gatewayId}/subscription/{notificationId}` | — | generic response |

The subscription model contains `deviceUniqueId`, `handle` (FCM token), `language`, `notificationId`, and `platform`.

Recognized FCM data keys are `message`, `loc-args`, `id_gateway`, and `id_message`. The app rejects a notification for another gateway. If `loc-args` contains `c100x@<gatewayId>.bs.iotleg.com`, or if `id_message` is absent, it starts the SIP service and refreshes registration. Other confirmed message IDs are `IP_CHANGE`, `TOPOLOGY_CHANGE`, `DELETE_GW`, `Pending user consent for download`, and `Pending user consent for installation`.

FCM is therefore a wake-up optimization, not the source of the SIP call itself. A permanently running Home Assistant process can maintain SIP registration directly and does not need to impersonate an Android FCM installation.

### Device management and firmware

| Method | Path | Request | Response |
|---|---|---|---|
| POST | `devicemanagement/api/v2.0/modules` | `Module` | device-post response |
| DELETE | `devicemanagement/api/v2.0/modules/{moduleId}` | — | generic response |
| GET | `devicemanagement/api/v2.0/modules/{moduleId}/firmware` | — | `Firmware` |
| POST | `.../firmware/{version}/download` | scheduled download timestamp | generic response |
| POST | `.../firmware/{version}/install` | scheduled install timestamp | generic response |

The APK also contains Netatmo-related command routes `commands/setLogin`, `setPresence`, `setStatus`, `getCameras`, and `getStatus`. They are separate accessory functions and are not the Classe 100X strike protocol.

### Consent and application support

The app also calls `termsandconditions/api/V2.0` for all-consent and consent-document operations, and user-service v3 endpoints for `/welcome` and `/consents/account`. These are account lifecycle/UI functions, not required for ongoing intercom operation.

## Local commissioning protocol

The APK contains a second JSON-RPC implementation used during local discovery and commissioning. It is independent of SIP commands and connects by TCP to the gateway's LAN IP on port `50003` (**Confirmed**).

The socket is upgraded to TLS-PSK. The PSK identity is the QR-code `macaddr` and the hexadecimal PSK is the QR-code `pskkey`; these are installation secrets and must never be published. JSON requests are written as newline-terminated UTF-8 strings. The client reads one response and closes the connection.

Confirmed local methods are:

| Method | Purpose | Important fields |
|---|---|---|
| `gateway.getDeviceIdentity` | Probe an IP and validate a Classe 100X | response `productCode`, `macAddress`, `commissioned`; app requires product code `99` |
| `plant.getDeviceInfo` | Read gateway hardware/firmware information | response `modules[]` with `HardwareId`, `device`, firmware/hardware versions, MAC |
| `gateway.setWifiNetwork` | Configure Wi-Fi during onboarding | `ssid`, `passphrase` |
| `plant.setBelongToPlant` | Associate gateway with the selected cloud plant | nested topology/plant `id`, `name`, `type` |
| `plant.addConnection` | Install the Azure IoT Hub connection | hostname, device ID, MQTT protocol, primary/secondary keys |

All use JSON-RPC `2.0`, a random non-negative integer encoded as a string for request `id`, and a one-element `params` array. Parameter models default to version `v1.0`.

This local protocol explains why the official app may know the gateway without asking the user for a LAN address: onboarding obtains the address from the QR/access-point and network discovery flow. It does **not** explain strike selection. Runtime remote strike commands still target the per-gateway SIP URI and carry the cloud lock module ID in `receiver.plant.coal.id`.

## SIP transport and registration

Remote operation uses Linphone over TLS (**Confirmed**):

- proxy/registrar: `vdesip.bs.iotleg.com`
- transport: TLS
- identity: the provisioned SIP URI
- authentication: SIP account username/password, with the provisioned client certificate and private key
- registrar/proxy address: `sip:vdesip.bs.iotleg.com;transport=tls`
- authentication realm/domain: `<gatewayId>.bs.iotleg.com`
- app registration expiry: 5,184,000 seconds; on successful registration the app schedules an hourly account refresh
- SIP user agent: `VctLinphoneService/1.8.4` for this release
- official app push contact parameters: `pn-param=door-entry-for-classe-100x16e;pn-provider=fcm;pn-timeout=0;pn-prid=<FCM-token>`
- media encryption is enabled and mandatory by default; the stored preference defaults to Linphone enum value `1`

The app restricts acceptable SIP certificate subjects to the selected per-gateway host and known production/QA SIP proxy names. The notable production names are `<gatewayId>.bs.iotleg.com`, `vdesip.bs.iotleg.com`, and numbered `vde-sipN.bs.iotleg.com` hosts.

The recovered remote-account construction order is also explicit. The app creates the identity from the provisioned full SIP URI, creates the server address from `sip:vdesip.bs.iotleg.com;transport=tls`, sets the proxy expiry, installs CA/client-certificate/private-key material on the core, adds digest authentication for the identity username in realm/domain `<gatewayId>.bs.iotleg.com`, sets the same proxy URI as an outbound route, adds push contact parameters, enables registration, adds the proxy configuration, and makes it the default. Strike chat rooms are therefore created under that selected default identity and outbound route, not as unrelated stateless TLS messages.

The packaged Linphone factory configuration adds these confirmed defaults:

- server-certificate verification enabled;
- generic hostname verification disabled, with the application installing its explicit SIP certificate-subject regular expression instead;
- SIP UDP/TCP/TLS listening ports disabled (`-1`), so the client uses its outbound connection;
- IPv6 and automatic network-state monitoring enabled;
- SIP keepalive period 30,000 ms;
- one concurrent call maximum;
- RTP audio port 7076 and video port 9078;
- MTU 1300, audio/video jitter compensation 60, no-RTP timeout 30 seconds, UPnP disabled;
- STUN default `stun.linphone.org` with DNS SRV enabled;
- QVGA default video size and Android OpenGL display.

The signed arm64 split provides additional native-build evidence. It contains only `lib/arm64-v8a/liblinphone.so`; strings and exported symbols identify:

- wrapper build `linphone-sdk version 3.0.3 (build 20251030)`;
- liblinphone/oRTP/mediastreamer component version `5.4.0`;
- the JNI entry points used by the recovered Java binding, including `Java_org_linphone_core_ChatRoomImpl_createMessage` and `linphone_chat_room_create_message`.

The apparently different `3.0.3` and `5.4.0` values are both emitted by this same vendor-signed binary. They likely distinguish the vendor SDK product build from its upstream Linphone component baseline; neither should be silently replaced with the version of a system Linphone package.

For portal accounts the app loads the CA chain returned by `CACerts` into Linphone as root CA data, and separately loads the issued client certificate and local EC private key. Disabling server verification or discarding that CA chain is therefore not an exact or security-equivalent implementation of the official client.

The app does not hard-code a SIP service port; its factory configuration enables DNS SRV. A read-only DNS check on 2026-07-29 returned three `_sips._tcp.vdesip.bs.iotleg.com` targets, all on port `5228`, with priorities 10, 20, and 80. `vdesip.bs.iotleg.com` also resolved through a `vde-sipN` node. Thus 5228 is currently verified but should be discovered through SRV to preserve proxy failover and future server changes.

A read-only TLS handshake on the same date returned a server certificate with subject `C=FR, O=LEGRAND, OU=VDE, CN=vdesip.bs.iotleg.com`, SAN `*.bs.iotleg.com`, issuer `Legrand Non-Public - PROD`, and validity 2026-06-26 through 2027-06-26. These values are operational observations, not stable constants; an implementation should validate the returned chain and allowed identity rather than pinning that leaf certificate or its dates.

For local Wi-Fi it can prefer a discovered/configured local SIP server, then falls back to remote. The default development local identity values visible in preferences (`user1`, `12345`, `127.0.0.1`, `sip.c100x.org`) must not be treated as production credentials.

## Ringing, video, and audio

An incoming ring is a SIP `INVITE` (**Confirmed**). The app verifies that its remote URI contains `c100x@<gatewayId>.bs.iotleg.com`; calls from another origin are declined as busy. It broadcasts call state internally and opens its call UI.

For incoming calls it accepts early media before the user answers. When the remote offer enables video, the intended media configuration is receive-only video with audio initially inactive. On answer, it accepts with receive-only video; normal external-unit calls use send/receive audio. The application:

- sets a 70-second in-call timeout for door calls;
- enables low-bandwidth mode when the network helper considers it necessary;
- uses receive-only video, so the phone does not send camera video;
- can send and receive audio for two-way conversation;
- can update a call with custom SDP attributes `DEVADDR=<camera-address>` and `CAMERASLIDING=2` to select/cycle cameras;
- supports a `TVCC=1` attribute that disables audio for camera-only viewing.

The app's “view entrance” operation starts an outgoing SIP call to the short target `c100x`. Linphone resolves it in the active identity domain, yielding `sip:c100x@<gatewayId>.bs.iotleg.com`. The SDP carries `DEVADDR=<selected EU module id>`. Netatmo/TVCC entries add `TVCC=1`. The remote answer can return `DEVADDR`, which the UI records as the active entrance/camera. This is separate from the strike receiver but uses the same cloud module-ID addressing convention.

Exact negotiated codecs, payload types, ICE behavior, and SRTP keying are **Unknown** from this high-level Java trace because those details are delegated to the bundled Linphone native library and runtime SDP negotiation. They should be captured from a consented test call before claiming media compatibility.

## Door release and other JSON-RPC commands

The official app does **not** use the generic cloud `POST .../modules/{id}/commands` route for its primary Classe 100X strike button. It sends a SIP instant message to:

```text
sip:c100x@<gateway-module-id>.bs.iotleg.com
```

The body is compact JSON-RPC 2.0. For a strike module:

```json
{
  "jsonrpc": "2.0",
  "id": "<non-negative random 32-bit integer as a string>",
  "method": "lock.setStatus",
  "params": [
    {
      "status": "open",
      "receiver": {
        "plant": {
          "coal": {
            "id": "<lock-module-id>"
          }
        }
      }
    }
  ]
}
```

The application passes this JSON string directly to Linphone `ChatRoom.createMessage(String)` and calls `send()`. It does not call `ChatMessage.setContentType`, add custom SIP headers, or wrap the body in an app-defined envelope. The corresponding native entry point is the plain-message constructor and the bundled native library contains the `text/plain` media type. Consequently `Content-Type: text/plain` is the best-supported reconstruction. It remains **Inferred**, rather than packet-level **Observed**, until a redacted official-app SIP trace confirms the serialized request.

The command actuates the electric strike for its configured pulse; it does not represent persistent deadbolt state. It may be sent without a preceding ring/call, matching the official app’s standalone release button.

There are two confirmed UI paths:

- On the home page, the app creates one release slider for every aligned `Lock` device and passes that device's cloud module ID and CID `10060` to the command method. This is the standalone release path relevant to Home Assistant.
- In the active-call screen, the release slider has no concrete device object. It invokes the session/default CID `10060` with a null receiver ID, leaving the active intercom session to select its associated strike.

The Home Assistant button is not in a SIP call, so it must reproduce the first path with the selected lock module ID; it must not send the in-call null-receiver form.

The staircase-light request uses method `light.setStatus`, status `on`, and—despite the name—its serializer retains the same `receiver.plant.coal.id` branch while excluding `plant.module`. `gateway.sendLogs` does the opposite: it excludes `coal`, retains the `module` branch, and has no explicit module argument at its call site. Staircase light is intentionally outside this integration’s requested scope.

The app requires SIP registration state `Ok`, obtains a chat room for the per-gateway destination, verifies that the chat room’s local identity equals the selected SIP user, recreates it on mismatch, then sends the message. `ChatRoom.createMessage(String)` delegates content framing to Linphone; the Java code does not explicitly assign a content type. A JSON-RPC response model exists with `jsonrpc`, numeric `id`, boolean `result`, or `error {code,message}`, but the command callback shown in the app is driven by Linphone message state.

Important limitation: SIP `200 OK` or Linphone `Delivered` proves message acceptance/delivery at the SIP layer, not mechanical strike movement. The official callback waits up to 15 seconds, counts `NotDelivered` as failure, and returns success only when every tracked message reaches a terminal state with zero failures. It still has no confirmed physical feedback. A correct integration must report transport failure precisely and avoid claiming verified actuation without a separate device acknowledgement.

## Operational sequence

The minimum remote flow inferred from the app is:

1. Complete B2C sign-in and retain a refresh token securely.
2. Fetch the user’s plants and current topology.
3. Select the Classe 100X gateway module and retain all current lock modules associated with it.
4. Fetch or create a SIP account tied to a stable client ID.
5. Generate a local P-256 key and provision a SIP client certificate; renew it before the 30-day pre-expiry check fails.
6. Connect to the production SIP proxy over TLS and register the account.
7. Treat an authenticated gateway `INVITE` as a ring event; optionally negotiate early media/call media.
8. Send `lock.setStatus` by SIP `MESSAGE` to the per-gateway URI for standalone or in-call strike release.
9. Reconcile topology periodically so disconnected/stale lock modules disappear without collapsing legitimate multi-lock installations.

## Safety and compatibility notes

- Never log OAuth tokens, SIP passwords, private keys, certificates, full topology payloads, or account identifiers.
- Never upload the generated private key; only upload its CSR.
- Do not expose a release entity as a stateful “unlocked” deadbolt. It is a momentary strike action.
- Do not test release automatically. Require an explicit user action even when a mechanical key lock prevents entry.
- Do not infer Classe 100X behavior from Classe 300X/300EOS or Home + Security integrations.
- The protocol is private and may change server-side without notice. HTTP/SIP error handling and reauthentication must be conservative.

## Live read-only verification (2026-07-29)

A direct test against a real Classe 100X account was performed outside Home Assistant. No `lock.setStatus` message was sent, no strike was actuated, and the media offer was receive-only. Identifiers and credentials are intentionally omitted.

- The gateway reported model `bs-classe100x`, firmware `1.5.8`, hardware `02.07.0`, `CONNECTED`, and `on`.
- The global and plant-scoped module endpoints both returned the same eight records: one gateway, three locks, one light, and three audio/video terminals. The three terminal roles were one `IU` and two `EU`. This confirms that multiple cloud lock records cannot be collapsed merely because the installation has one physical entrance; stale-record reconciliation needs stronger evidence.
- The account already had three SIP clients. Attempting to create a fourth returned HTTP 400, so the test reused the existing dedicated integration client without involving the Home Assistant runtime.
- Certificate provisioning with the recovered official-app headers, `sipuser` template, and `OU=C100X` succeeded. The client certificate SAN matched the SIP URI, its issuer was the Legrand production non-public CA, and its lifetime was approximately one year. The returned CA chain expires in 2036.
- The repository SIP client completed authenticated TLS/Digest registration successfully with the newly provisioned certificate.
- A receive-only monitoring `INVITE` targeting an `EU` terminal received the expected proxy `407`, followed by authenticated `200 OK`. The answer disabled audio (`m=audio 0`) and offered H.264 video over SRTP as `sendonly`. This proves direct camera-session signaling without a ring or strike command. The verifier failed before counting encrypted UDP packets, so end-to-end media reception and decoding remain unverified. An immediate retry received `486 Busy Here`, consistent with the first dialog still awaiting timeout.

The test also confirms the corrected certificate-header split documented above: `Authorization` carries the application token and `UserToken` carries the user access token.

## What remains unverified

Static analysis gives high confidence in endpoint construction and control flow, but it is not a substitute for a protocol capture. The following still require a user-authorized, redacted test session:

- full request/response schemas and optional fields returned by every cloud endpoint;
- packet-level confirmation of the inferred `text/plain` SIP `MESSAGE` content type and the final response sequence across every proxy node;
- encrypted RTP reception/decoding, NAT behavior across networks, and camera-switch responses;
- whether the gateway returns an application-level JSON-RPC result after strike execution;
- certificate lifetime and renewal behavior for every certificate template/account age.

Claims in this document should be updated from captured evidence, with personal data and credentials removed, rather than guessed.

## Reproducibility map

The following app-owned symbols were independently cross-checked. Names are those recovered by JADX and may be obfuscated, but their package and behavior make the evidence traceable:

| Area | Recovered symbol | Evidence |
|---|---|---|
| Production roots and keys | `p094k3.b` implementing `p094k3.a` | B2C policies, API roots, SIP proxy, application-token endpoint |
| HTTPS requests | `R2.a` | HTTP method, full path construction, headers, request/response class |
| SIP-account/certificate workflow | `U2.h1` | SIP URI construction, application token, CA chain, CSR template, sender model |
| Key and CSR handling | `p049f3.c` | P-256 key generation, subject, SAN, encrypted local files, 30-day validity check |
| SIP service | `com.legrandgroup.c100x.linphone.VctLinphoneService` | proxy setup, TLS materials, registration, gateway domain, command dispatch |
| Call manager | `com.legrandgroup.c100x.linphone.a` | origin validation, early media, answer/hangup, SDP attributes |
| Door widget | `com.legrandgroup.c100x.linphone.b` | concrete device ID/CID versus session-default release |
| JSON-RPC command serializer | `models.jsonrpc.JsonRpcKotlin`, `Action`, `CustomExclStrat1` | exact method/status/receiver shape and field exclusions |
| Cloud topology alignment | `p103l3.d` | device-type/CID mapping, module ID → device address, stale-device deletion |
| Push handling | `fcm.FirebaseMessaging` and `U2.Z` | FCM keys, gateway filtering, subscription lifecycle |
| Local TLS-PSK client | `p112m3.g` | port 50003, TLS-PSK identity/key conversion, newline JSON framing |
| Local JSON-RPC models | `btcommlib.domain.jsonRpc.*` | commissioning method names and schemas |
| Local probe | `p076i3.a` | product code 99 validation and MAC discovery |
| Linphone defaults | APK resources `res/raw/linphonerc_default` and `linphonerc_factory` | transport, verification, RTP, STUN, timeout, and video defaults |
| Native SIP/media implementation | signed split `config.arm64_v8a.apk`, `lib/arm64-v8a/liblinphone.so` | packaged architecture, build/component versions, JNI/plain-message entry points |

## Differences found in the current Home Assistant prototype

These are audit findings, not claims about the official app:

1. The prototype provisions template `sipuser-DIY` with `OU=DIY`; app 1.8.4 provisions `sipuser` with `OU=C100X`.
2. The prototype sends the user access token in both certificate headers; the app obtains an application token for `Authorization` and sends the user access token separately as `UserToken`.
3. The prototype does not fetch/install `CACerts` and disables SIP TLS server verification; the app installs that CA chain and verifies the server against an explicit subject allow-list.
4. The prototype hand-builds SIP requests. Header generation, routing, dialog/chat-room behavior, and content framing must be compared with Linphone behavior before considering it equivalent.
5. The prototype reports success on a final SIP 200 response. The app waits for Linphone's message delivery state with a 15-second timeout; neither mechanism proves physical actuation.
6. The prototype reports a ring on any received `INVITE`. The app rejects an incoming call unless its remote URI identifies `c100x@<selected-gateway>.bs.iotleg.com`.
7. The prototype responds `180` then `486` and does not negotiate media. The app accepts early media and maintains the call state needed for preview, video, and two-way audio.
8. The prototype adds PKCE to the B2C flow. PKCE is a desirable protection and the server accepts it, but it is not present in the recovered 1.8.4 reference flow and must be described as an intentional enhancement rather than reverse-engineered behavior.
9. The prototype advertises `ha-bticino-c100x/0.1`, registers for 600 seconds, and constructs `Via`/`Contact` around `127.0.0.1:5060`. The reference app identifies as `VctLinphoneService/1.8.4`, asks for 5,184,000 seconds, disables local listening ports, and lets Linphone construct transport/contact details for its outbound TLS flow. Registration success shows that the server tolerates some differences, but it does not prove that an independently constructed MESSAGE is routed and tracked identically.

These differences must be resolved from official-app behavior before video/audio or strike control is described as complete.
