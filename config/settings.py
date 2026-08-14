import os

SYMBOLS = ["BTCUSDT", "ETHUSDT"]

HTTP_HOST = "0.0.0.0"
HTTP_PORT = 8080

# Minimum number of core exchanges that must be connected for the
# cross-exchange confirmation component to hit 100% confidence.
MIN_EXCHANGES_FOR_FULL_CONFIDENCE = 4

# SQLite file backing forge/accounts (private exchange connections).
# FORGE_ENCRYPTION_KEY (see forge/accounts/crypto.py) is read directly
# from the environment where it's used, not exposed here, so it never
# ends up printed alongside the rest of these settings.
DB_PATH = os.getenv("FORGE_DB_PATH", "forge_accounts.db")
