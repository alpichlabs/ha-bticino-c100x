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

The app was inspected statically. No certificate, token, password, personal identifier, live-account result, or captured traffic is used as protocol evidence in this document. Decompiled names can be incomplete because the release is obfuscated.

Every behavioral statement below is directly represented by the signed application's bytecode, packaged resources, data models, or bundled native library. Inferences, live observations, implementation proposals, and behavior found only in other BTicino product generations are excluded.

### Applicability rule

A behavior is treated as Classe 100X evidence only when it is reachable from package `com.legrandgroup.c100x` in the vendor-signed 1.8.4 app or implemented by the native Linphone split shipped with that same signed app.

Names found only in Classe 300X projects, Home + Security/Netatmo integrations, or generic Linphone documentation are comparison material, not proof of Classe 100X behavior. `netatmo_cam` is an explicit topology type handled by the Classe 100X app for an auxiliary camera; its name does not move the intercom itself onto the newer Home + Security API generation.

### Firmware 1.5.8 compatibility

The Classe 100X app performs an explicit firmware check during full alignment. Its recovered predicate splits the gateway firmware string into three integers and requires major `>= 1`, minor `>= 5`, and patch `>= 8`. Firmware `1.5.8` therefore passes the exact app-side gate. The app also labels the locally discovered gateway model `bs-classe100x` and requires commissioning product code `99`.

No firmware replacement, shell access to the intercom, or C300X controller procedure appears in these application paths.

## Architecture

The app does not expose a single REST “door entry API.” It combines four systems:

1. Azure AD B2C authenticates the Legrand account and issues OAuth tokens.
2. Legrand HTTPS APIs return plants, topology modules, SIP accounts, push subscriptions, firmware information, and client certificates.
3. A mutually authenticated SIP-over-TLS session handles registration, calls, early video, audio, and JSON-RPC commands sent as SIP chat messages.
4. Firebase Cloud Messaging wakes or refreshes SIP registration when an incoming call is pending.

The gateway module ID, topology actuator module ID, SIP account, and phone/app client ID are represented by separate fields and models.

### Why the Classe 100X app contains Netatmo camera code

`netatmo_cam` is an optional camera type inside the Classe 100X topology. The app sends `netatmo.getStatus`, `netatmo.getCameras`, `netatmo.setStatus`, `netatmo.setLogin`, and `netatmo.setPresenceHome` JSON-RPC bodies through Device Management endpoints under `modules/<module-id>/commands/{getCameras,getStatus,setStatus,setLogin,setPresence}`. Returned cameras are then exposed as camera-only SIP viewing targets using `TVCC=1`.

This code path is separate from the Classe 100X strike path. The application continues to identify the gateway as `bs-classe100x`.

## Production service roots

These production roots are embedded in the application:

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

The APK also contains QA/pre-production endpoints; this reference lists only the production roots selected by its production configuration.

## OAuth authentication

The production app uses Azure AD B2C authorization-code authentication:

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

The application ID, API subscription key, and a separate application-level client credential are embedded in the distributable app. Their values are not reproduced here.

Access tokens are passed as `Authorization: Bearer <access-token>`. Some certificate and user operations additionally pass a token in `UserToken`. OAuth refresh tokens are used to renew access without repeating the interactive sign-in.

The recovered authorization library builds a conventional `response_type=code` request with client ID, redirect URI, and configured scopes, then exchanges the returned code with the redirect URI and public client ID. No `code_challenge` or `code_verifier` string or setter was found anywhere in the APK, so PKCE is not evidenced in app 1.8.4. The login WebView enables JavaScript, disables its cache, and removes previous cookies. Credentials are persisted under the logical key `azureb2c`; refresh uses the B2C token endpoint and public-client authentication without a client secret.

## Common HTTPS headers

Most JSON API calls use:

```http
Authorization: Bearer <user-access-token>
Ocp-Apim-Subscription-Key: <Door Entry application subscription key>
Content-Type: application/json
```

Certificate calls use the exact header split documented in [Client certificates](#client-certificates). Selected user-service calls also use `UserToken` according to their recovered call sites.

The general additional-header form is:

```http
UserToken: <token selected by the recovered call site>
```

The HTTP API manager contains a sanitizer for `sipPassword`, `access_token`, `cert`, client secrets, API keys, and passwords. Other recovered authentication code nevertheless includes debug statements that interpolate access and refresh tokens directly.

## HTTPS endpoint catalogue

Volley numeric methods in the APK map to GET=0, POST=1, PUT=2, DELETE=3, and PATCH=7. The following endpoint construction and response classes occur in the application. Bodies marked “model” are serialized model objects.

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

Most importantly, the official app sets both the local `deviceAddr` and the JSON-RPC receiver parameter from the cloud module's `id`. A `PrivateAddress` tag is parsed for `buttonId` and `visible` UI metadata in this flow. Values such as `21` or `22` nested in that tag are not used as the receiver of `lock.setStatus`.

The official lock query applies the following exact selection rule before it creates the release controls:

1. the aligned device CID must be `10060` (`Lock`);
2. `PrivateAddress.visible` must equal `1` or `2`;
3. all matching locks are retained and ordered by numeric `PrivateAddress.buttonId`.

The application therefore creates one release control for every matching visible lock. Records with another visibility value are not used to create release controls.

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

Certificate creation in the official app is as follows:

1. Generate an EC key pair on curve `prime256v1`/P-256 locally.
2. Keep the private key local; only a PKCS#10 CSR is uploaded.
3. Sign the CSR with SHA-256 with ECDSA.
4. Use the subject `EMAILADDRESS=<account-email>, C=FR, ST=France, L=Paris, O=LEGRAND, OU=C100X, CN=<client-id>`.
5. Add a URI subject alternative name `sip:<sip-uri>`.
6. Convert the PEM CSR to DER and Base64-encode it for JSON.
7. Submit it with template `sipuser` and sender `{system: "information", addressType: "addressLocation", plant: <Plant>}`.
8. Store the returned client certificate and CA chain with the private key for SIP TLS.

The certificate calls first obtain a separate application token through the app's embedded client-credentials flow. The official request helper `u(userToken, bearerToken, key)` places the **application token** in `Authorization: Bearer ...` and the **user access token** in `UserToken`. This ordering is confirmed by both `U2.h1` call sites and `R2.a.u`; treating both headers as the same token, or reversing them, is not an exact reproduction of the official app.

The official app checks certificate validity 30 days into the future (`now + 2,592,000,000 ms`). If that check fails, it deletes the stored key/certificate material so the alignment/provisioning flow can create a new set.

### Push notifications

| Method | Path | Request | Response |
|---|---|---|---|
| GET | `vde/push/v1.0/devices/{gatewayId}/subscription` | — | `PushNotification[]` |
| POST | same path | `PushNotification` | `PushNotification` |
| DELETE | `vde/push/v1.0/devices/{gatewayId}/subscription/{notificationId}` | — | generic response |

The subscription model contains `deviceUniqueId`, `handle` (FCM token), `language`, `notificationId`, and `platform`.

Recognized FCM data keys are `message`, `loc-args`, `id_gateway`, and `id_message`. The app rejects a notification for another gateway. If `loc-args` contains `c100x@<gatewayId>.bs.iotleg.com`, or if `id_message` is absent, it starts the SIP service and refreshes registration. Other confirmed message IDs are `IP_CHANGE`, `TOPOLOGY_CHANGE`, `DELETE_GW`, `Pending user consent for download`, and `Pending user consent for installation`.

FCM starts or refreshes the SIP service; the incoming call itself is handled by Linphone.

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

The APK contains a second JSON-RPC implementation used during local discovery and commissioning. It is independent of SIP commands and connects by TCP to the gateway's LAN IP on port `50003`.

The socket is upgraded to TLS-PSK. The PSK identity is the QR-code `macaddr` and the hexadecimal PSK is the QR-code `pskkey`. JSON requests are written as newline-terminated UTF-8 strings. The client reads one response and closes the connection.

Local methods present in this path are:

| Method | Purpose | Important fields |
|---|---|---|
| `gateway.getDeviceIdentity` | Probe an IP and validate a Classe 100X | response `productCode`, `macAddress`, `commissioned`; app requires product code `99` |
| `plant.getDeviceInfo` | Read gateway hardware/firmware information | response `modules[]` with `HardwareId`, `device`, firmware/hardware versions, MAC |
| `gateway.setWifiNetwork` | Configure Wi-Fi during onboarding | `ssid`, `passphrase` |
| `plant.setBelongToPlant` | Associate gateway with the selected cloud plant | nested topology/plant `id`, `name`, `type` |
| `plant.addConnection` | Install the Azure IoT Hub connection | hostname, device ID, MQTT protocol, primary/secondary keys |

All use JSON-RPC `2.0`, a random non-negative integer encoded as a string for request `id`, and a one-element `params` array. Parameter models default to version `v1.0`.

This local commissioning protocol is distinct from the runtime remote strike path, which targets the per-gateway SIP URI and carries the cloud lock module ID in `receiver.plant.coal.id`.

## SIP transport and registration

Remote operation uses Linphone over TLS:

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

The apparently different `3.0.3` and `5.4.0` values are both emitted by this same vendor-signed binary. Their relationship is not defined by the application and is not interpreted further here.

For portal accounts the app loads the CA chain returned by `CACerts` into Linphone as root CA data, and separately loads the issued client certificate and local EC private key. The app does not hard-code a SIP service port; its factory configuration enables DNS SRV.

For local Wi-Fi it can prefer a discovered/configured local SIP server, then falls back to remote. The application also contains default development preference values: `user1`, `12345`, `127.0.0.1`, and `sip.c100x.org`.

## Ringing, video, and audio

An incoming ring is a SIP `INVITE`. The app verifies that its remote URI contains `c100x@<gatewayId>.bs.iotleg.com`; calls from another origin are declined as busy. It broadcasts call state internally and opens its call UI.

For incoming calls it accepts early media before the user answers. When the remote offer enables video, the intended media configuration is receive-only video with audio initially inactive. On answer, it accepts with receive-only video; normal external-unit calls use send/receive audio. The application:

- sets a 70-second in-call timeout for door calls;
- enables low-bandwidth mode when the network helper considers it necessary;
- uses receive-only video, so the phone does not send camera video;
- can send and receive audio for two-way conversation;
- can update a call with custom SDP attributes `DEVADDR=<camera-address>` and `CAMERASLIDING=2` to select/cycle cameras;
- supports a `TVCC=1` attribute that disables audio for camera-only viewing.

The app's “view entrance” operation starts an outgoing SIP call to the short target `c100x`. Linphone resolves it in the active identity domain, yielding `sip:c100x@<gatewayId>.bs.iotleg.com`. The SDP carries `DEVADDR=<selected EU module id>`. Netatmo/TVCC entries add `TVCC=1`. The remote answer can return `DEVADDR`, which the UI records as the active entrance/camera. This is separate from the strike receiver but uses the same cloud module-ID addressing convention.

Codec ordering, payload types, NAT traversal, SRTP keying, SIP dialog state, and RTP processing are delegated to the bundled Linphone stack. The Java application does not create a manual SIP `INVITE`, choose an H.264 payload type, calculate SRTP keys, or parse RTP packets itself.

The app's outgoing Classe 100X monitoring sequence is:

1. require Linphone registration state `Ok` and an active network;
2. interpret the short destination `c100x` through the default proxy identity;
3. create fresh `CallParams` and apply the app's quality helper;
4. enable video with direction `RecvOnly`;
5. set audio to `SendRecv` for a normal `EU`, or `Inactive` only for a `TVCC=1` camera;
6. add `DEVADDR=<selected visible EU module id>` as a custom session-level SDP attribute;
7. call Linphone `inviteAddressWithParams` and retain its returned call object;
8. request notification of the next decoded video frame and attach a call listener;
9. render decoded video through Linphone's native video-window output;
10. terminate calls with no audio or video download bandwidth for ten seconds.

For a monitoring call started from `VctHomepageFragment`, the call-state handler invokes `setAudioMuted(true)` and selects speaker output. `setAudioMuted(true)` delegates to `Core.setMicEnabled(false)`. The normal external-unit call nevertheless retains `AudioDirection.SendRecv`; received audio continues through Linphone while microphone capture is disabled. The UI checkbox reverses this by calling `Core.setMicEnabled(true)` on the same call.

The video window is an `AndroidVideoWindowImpl` backed by `FixedAspectGL2JNIView` (or `FixedAspectSurfaceView` for one legacy device model). The app initially makes the rendering view transparent, calls `requestNotifyNextVideoFrameDecoded()`, and reveals it when `onNextVideoFrameDecoded()` fires.

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

The application passes this JSON string directly to Linphone `ChatRoom.createMessage(String)` and calls `send()`. It does not call `ChatMessage.setContentType`, add custom SIP headers, or wrap the body in an app-defined envelope. Content framing beyond that Java call is delegated to the bundled Linphone library and is not specified here.

The home-page release control can send this command without a preceding incoming call. The application labels the operation as a door release and sends `status: "open"`; this path contains no persistent lock-state model.

There are two UI paths:

- On the home page, the app creates one release slider for every aligned visible `Lock` device and passes that device's cloud module ID and CID `10060` to the command method.
- In the active-call screen, the release slider has no concrete device object. It invokes the session/default CID `10060` with a null receiver ID, leaving the active intercom session to select its associated strike.

The staircase-light request uses method `light.setStatus`, status `on`, and its serializer retains the same `receiver.plant.coal.id` branch while excluding `plant.module`. `gateway.sendLogs` excludes `coal`, retains the `module` branch, and has no explicit module argument at its call site.

The app requires SIP registration state `Ok`, obtains a chat room for the per-gateway destination, verifies that the chat room’s local identity equals the selected SIP user, recreates it on mismatch, then sends the message. `ChatRoom.createMessage(String)` delegates content framing to Linphone; the Java code does not explicitly assign a content type. A JSON-RPC response model exists with `jsonrpc`, numeric `id`, boolean `result`, or `error {code,message}`, but the command callback shown in the app is driven by Linphone message state.

The command callback waits up to 15 seconds, counts Linphone `NotDelivered` as failure, and reports success only when every tracked message reaches a terminal state with zero failures. The recovered application path contains no separate sensor reading that confirms physical strike movement.

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
