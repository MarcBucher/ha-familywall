"""Constants for the FamilyWall integration."""

from datetime import timedelta

DOMAIN = "familywall"

CONF_LISTS = "lists"

API_BASE_URL = "https://api.familywall.com/api"
SCAN_INTERVAL = timedelta(seconds=60)

# Only the most recently completed items are shown; older ones stay in FamilyWall
# (and are out of reach of "remove completed" in Home Assistant).
MAX_COMPLETED_ITEMS = 20
