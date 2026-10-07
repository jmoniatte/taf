from importlib.metadata import PackageNotFoundError, version

REPOSITORY_URL = "https://github.com/jmoniatte/taf"

try:
    __version__ = version("taf")
except PackageNotFoundError:
    __version__ = "0.0.0"
