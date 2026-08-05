"""Exception types raised by yaml-io.

All inherit from :class:`YamlIOError`, which in turn inherits from
``ValueError`` so that callers written against earlier versions of this
library (which raised bare ``ValueError``) keep working.
"""


class YamlIOError(ValueError):
    """Base class for every error raised by yaml-io."""


class CircularImportError(YamlIOError):
    """A file transitively imports itself."""


class ImportResolutionError(YamlIOError):
    """An ``#!import`` target could not be read."""


class DirectiveError(YamlIOError):
    """A ``#!import`` or ``#!export`` line is malformed."""


class ExportError(YamlIOError):
    """An ``#!export`` names an anchor that does not exist."""


class AnchorCollisionError(YamlIOError):
    """Two distinct anchors compete for the same name."""


__all__ = [
    "YamlIOError",
    "CircularImportError",
    "ImportResolutionError",
    "DirectiveError",
    "ExportError",
    "AnchorCollisionError",
]
