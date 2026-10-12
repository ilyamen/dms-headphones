from .galaxy_buds import GalaxyBudsDriver
from .ugreen import UgreenDriver

# Add new drivers here. The first one whose `match` accepts a device handles it.
DRIVERS = [UgreenDriver, GalaxyBudsDriver]


def find_driver(info):
    for driver in DRIVERS:
        model = driver.match(info)
        if model:
            return driver, model
    return None, None
