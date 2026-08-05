"""yaml-io: import YAML anchors across files and re-export them for re-use.

Importing this package has no side effects. It does not patch PyYAML.

    import yaml_io

    data = yaml_io.load("config.yml")
    for doc in yaml_io.load_all("multi.yml"):
        ...

The loader also works through PyYAML directly::

    import yaml, yaml_io

    with open("config.yml") as f:
        data = yaml.load(f, Loader=yaml_io.YamlIOLoader)
"""

import os

from .errors import (
    AnchorCollisionError,
    CircularImportError,
    DirectiveError,
    ExportError,
    ImportResolutionError,
    YamlIOError,
)
from .loader import YamlIOLoader, load_imports_exports, parse_directives

__version__ = "0.2.1"


def _open(source):
    """Return ``(text, name)`` for a path, an open file, or raw YAML text."""
    if isinstance(source, (str, bytes, os.PathLike)) and _looks_like_path(source):
        path = os.fspath(source)
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read(), path

    if hasattr(source, "read"):
        return source.read(), getattr(source, "name", None)

    return source, None


# Suffixes that mark a single-line string as a filename rather than YAML text.
_PATH_SUFFIXES = (".yml", ".yaml")


def _looks_like_path(source) -> bool:
    if isinstance(source, os.PathLike):
        return True
    if isinstance(source, bytes):
        return False
    if "\n" in source:
        return False
    # An existing file is unambiguous. Otherwise treat a lone `*.yml` as a path
    # so a typo raises FileNotFoundError instead of quietly parsing as the
    # string "congif.yml".
    return os.path.exists(source) or source.endswith(_PATH_SUFFIXES)


def load(source):
    """Load a single-document YAML file, resolving imports and exports.

    *source* may be a path, an open file object, or a YAML string. Relative
    imports resolve against the file's directory, or the working directory when
    the source has no path.
    """
    text, name = _open(source)
    loader = YamlIOLoader(text, name=name)
    try:
        data = loader.get_single_data()
        # Nothing imports the entry file, but validating its exports still
        # turns a typo into an error instead of silence.
        loader.exported_anchors()
        return data
    finally:
        loader.dispose()


def load_all(source):
    """Load every document in a YAML stream, resolving imports and exports.

    Returns a list. Imported anchors are available in all documents; anchors
    defined inside one document do not leak into the next, matching YAML's own
    scoping rules.
    """
    text, name = _open(source)
    loader = YamlIOLoader(text, name=name)
    try:
        documents = []
        while loader.check_data():
            documents.append(loader.get_data())
        loader.exported_anchors()  # validate exports; see load()
        return documents
    finally:
        loader.dispose()


__all__ = [
    "load",
    "load_all",
    "YamlIOLoader",
    "load_imports_exports",
    "parse_directives",
    "YamlIOError",
    "CircularImportError",
    "ImportResolutionError",
    "DirectiveError",
    "ExportError",
    "AnchorCollisionError",
    "__version__",
]
