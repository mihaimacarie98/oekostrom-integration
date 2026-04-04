"""Constants for the oekostrom AG integration."""

DOMAIN = "oekostrom"
VERSION = "1.0.0"

CONF_USERNAME = "username"
CONF_PASSWORD = "password"

API_BASE = "https://mein.oekostrom.at"
API_PORTAL_PAGE = f"{API_BASE}/a-p"
API_PROXY = f"{API_BASE}/wp-content/plugins/oekostrom-kundenportal/includes/api-proxy.php"
API_ENV = "sdk-prod"
PORTAL_NAME = "OEKOSTROM"

USER_AGENT = f"HomeAssistant-oekostrom/{VERSION} (https://github.com/hackerman/hacs-oekostrom)"
