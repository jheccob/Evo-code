class StatsService:
    def __init__(self):
        self.stats = {}

    def add_statistic(self, key, value):
        if key in self.stats:
            self.stats[key].append(value)
        else:
            self.stats[key] = [value]

    def get_statistic(self, key):
        return self.stats.get(key, None)

    def consolidated_stats(self):
        consolidated = {key: sum(values) / len(values) for key, values in self.stats.items()}
        return consolidated
