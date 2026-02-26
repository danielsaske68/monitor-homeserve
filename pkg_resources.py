class DistributionNotFound(Exception):
    pass


def get_distribution(name):
    class Fake:
        version = "0.0"
    return Fake()


def iter_entry_points(group, name=None):
    return []
