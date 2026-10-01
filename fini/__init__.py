from importlib.metadata import PackageNotFoundError, version

REPOSITORY_URL = "https://github.com/jmoniatte/fini"

try:
    __version__ = version("fini")
except PackageNotFoundError:
    __version__ = "0.0.0"
