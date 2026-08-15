import os

SYMBOLS = ["BTCUSDT", "ETHUSDT"]

HTTP_HOST = "0.0.0.0"
# Render (and most PaaS platforms) assign the port dynamically via $PORT
# and expect the app to bind to it - 8080 is only the local-dev default.
HTTP_PORT = int(os.getenv("PORT", 8080))

# Minimum number of core exchanges that must be connected for the
# cross-exchange confirmation component to hit 100% confidence.
MIN_EXCHANGES_FOR_FULL_CONFIDENCE = 4

# SQLite file backing forge/accounts (private exchange connections).
# FORGE_ENCRYPTION_KEY (see forge/accounts/crypto.py) is read directly
# from the environment where it's used, not exposed here, so it never
# ends up printed alongside the rest of these settings.
DB_PATH = os.getenv("FORGE_DB_PATH", "forge_accounts.db")

# Bearer token required on every endpoint except /health and /signal/*
# (see forge/auth.py). None disables auth entirely - only acceptable
# for local-only use, never once this is reachable beyond localhost/a
# trusted network.
API_KEY = os.getenv("FORGE_API_KEY")
