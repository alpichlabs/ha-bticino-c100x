"""Constants for the BTicino C100X integration."""

from homeassistant.const import Platform

DOMAIN = "bticino_c100x"
PLATFORMS = [Platform.BINARY_SENSOR, Platform.EVENT, Platform.LOCK, Platform.SENSOR]

CONF_HOME_ID = "home_id"
CONF_GATEWAY_ID = "gateway_id"
CONF_LOCK_IDS = "lock_ids"

API_BASE = "https://api.developer.legrand.com"
API_SUBSCRIPTION_KEY = "f36968e522bf4ec3877fa491109d3d14"

B2C_BASE = "https://eliotclouduamprd.b2clogin.com"
B2C_TENANT = "EliotClouduamprd.onmicrosoft.com"
B2C_POLICY = "B2C_1_DoorEliot-C100X-SignUporSignIn"
B2C_CLIENT_ID = "7d11af71-ab98-4832-aa62-6b00bff3bcc8"
B2C_REDIRECT_URI = "com.legrandgroup.c100x://oauth2redirect"
B2C_SCOPE = "openid offline_access https://EliotClouduamprd.onmicrosoft.com/security/access.full"
B2C_USER_AGENT = "NetatmoApp(DoorEntry/v1.8.4) Android(13/Google/sdk_gphone64_arm64)"

SIP_SERVER = "vdesip.bs.iotleg.com"
SIP_PORT = 5228
SIP_REGISTER_EXPIRES = 600
SIP_REREGISTER_SECONDS = 480
SIP_RECONNECT_SECONDS = 10
SIP_USER_AGENT = "ha-bticino-c100x/0.1"

# Legrand's public third-party Door Entry certificate profile.
CERTIFICATE_TEMPLATE = "sipuser-DIY"
CERTIFICATE_ORGANIZATIONAL_UNIT = "DIY"
CERTIFICATE_RENEWAL_DAYS = 30

RING_ACTIVE_SECONDS = 5
EVENT_RING = f"{DOMAIN}_ring"
STORAGE_VERSION = 1
