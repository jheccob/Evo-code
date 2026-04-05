class MarketDataService:
    def __init__(self):
        self.cache = {}

    def get_data(self, symbol):
        # Check if data is in cache
        if symbol in self.cache:
            return self.cache[symbol]

        # Simulated data retrieval
        data = self.fetch_data(symbol)

        # Cache the data before returning
        self.cache[symbol] = data
        return data

    def fetch_data(self, symbol):
        # Simulate fetching market data (placeholder implementation)
        return {"symbol": symbol, "price": 100.0}  # Dummy data

    def clear_cache(self):
        self.cache.clear()  # Method to clear cache
