SYMBOLS = ["BTCUSDT", "ETHUSDT"]

HTTP_HOST = "0.0.0.0"
HTTP_PORT = 8080

# Minimum number of core exchanges that must be connected for the
# cross-exchange confirmation component to hit 100% confidence. One of
# the 4 configured exchanges (usually Binance) being temporarily down
# (e.g. rate-limit ban) shouldn't cap confidence at 75 for hours.
MIN_EXCHANGES_FOR_FULL_CONFIDENCE = 3
