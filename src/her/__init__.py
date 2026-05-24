"""her: a 'Her'-style multimodal assistant."""
from importlib.metadata import PackageNotFoundError, version as _pkg_version

try:
    __version__ = _pkg_version("her")
except PackageNotFoundError:  # editable install without metadata
    __version__ = "0.0.0"

