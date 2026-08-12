import os

SUPERSET_SECRET_KEY = os.getenv("SUPERSET_SECRET_KEY", "smartcity_superset_secret_key_2026")

# Completely disable Talisman and FAB security headers to allow iframe embedding anywhere
TALISMAN_ENABLED = False
FAB_ADD_SECURITY_HEADERS = False
HTTP_HEADERS = {}
OVERRIDE_HTTP_HEADERS = {}
PUBLIC_ROLE_LIKE = "Admin"
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_HTTPONLY = False
SESSION_COOKIE_SECURE = False
ENABLE_JAVASCRIPT_CONTROLS = True
