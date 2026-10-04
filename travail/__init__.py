from importlib.metadata import PackageNotFoundError, version

REPOSITORY_URL = "https://github.com/jmoniatte/travail"

try:
    __version__ = version("travail")
except PackageNotFoundError:
    __version__ = "0.0.0"
