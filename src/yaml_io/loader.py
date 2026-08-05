"""Directive parsing and the import/export aware YAML loader."""

import os
import re

from yaml.composer import Composer
from yaml.constructor import SafeConstructor
from yaml.parser import Parser
from yaml.reader import Reader
from yaml.resolver import Resolver

from .errors import (
    AnchorCollisionError,
    CircularImportError,
    DirectiveError,
    ExportError,
    ImportResolutionError,
)
from .scanner import DottedAliasScanner

# Directives are recognised only at column 0. That is a sufficient guard against
# false positives inside block scalars, whose content must always be indented.
_IMPORT_RE = re.compile(
    r'^#!import[ \t]+(?:"([^"]+)"|\'([^\']+)\'|(\S+))'
    r"[ \t]+as[ \t]+([A-Za-z_][A-Za-z0-9_-]*)[ \t]*$"
)
_EXPORT_RE = re.compile(r"^#!export[ \t]+(.+?)[ \t]*$")

# Catches a directive that failed the strict patterns above, so a typo becomes a
# clear error instead of being silently treated as an ordinary YAML comment.
_LOOSE_RE = re.compile(r"^#!(import|export)\b")

_EXPORT_NAME_RE = re.compile(
    r"^(?:([A-Za-z_][A-Za-z0-9_-]*)\.)?([A-Za-z_][A-Za-z0-9_-]*|\*)$"
)


class Import:
    """One resolved ``#!import`` directive."""

    __slots__ = ("path", "prefix", "line")

    def __init__(self, path: str, prefix: str, line: int):
        self.path = path
        self.prefix = prefix
        self.line = line


def parse_directives(text: str) -> tuple[str, list[Import], list[str]]:
    """Split *text* into YAML content, imports, and export names.

    Directive lines are replaced with empty lines rather than removed, so line
    and column numbers in parser errors still match the original file.
    """
    kept: list[str] = []
    imports: list[Import] = []
    exports: list[str] = []

    for lineno, line in enumerate(text.splitlines(), start=1):
        match = _IMPORT_RE.match(line)
        if match:
            dquoted, squoted, bare, prefix = match.groups()
            imports.append(Import(dquoted or squoted or bare, prefix, lineno))
            kept.append("")
            continue

        match = _EXPORT_RE.match(line)
        if match:
            for name in match.group(1).split(","):
                name = name.strip()
                if name:
                    exports.append(name)
            kept.append("")
            continue

        if _LOOSE_RE.match(line):
            raise DirectiveError(
                f"line {lineno}: malformed directive: {line.strip()!r}\n"
                "  expected: #!import <path> as <prefix>\n"
                "        or: #!export <name>[, <name>...]"
            )

        kept.append(line)

    return "\n".join(kept), imports, exports


class YamlIOLoader(
    Reader, DottedAliasScanner, Parser, Composer, SafeConstructor, Resolver
):
    """A ``SafeLoader`` that resolves ``#!import`` and ``#!export`` directives.

    Usable directly with PyYAML::

        with open("config.yml") as f:
            data = yaml.load(f, Loader=YamlIOLoader)

    The stream is read in full and its directives resolved during ``__init__``,
    which is what lets the loader recover the base directory for relative
    imports from ``stream.name``.
    """

    def __init__(self, stream, name=None, _stack=None, _cache=None):
        if hasattr(stream, "read"):
            name = name or getattr(stream, "name", None)
            text = stream.read()
        else:
            text = stream

        if isinstance(text, bytes):
            text = text.decode("utf-8")

        base_dir = os.path.dirname(os.path.abspath(name)) if name else os.getcwd()

        content, imports, exports = parse_directives(text)
        self._imported_anchors = _resolve_imports(
            imports,
            base_dir,
            name,
            _stack if _stack is not None else [],
            _cache if _cache is not None else {},
        )
        self._export_names = exports

        # Anchors defined by this file, accumulated across every document.
        self.defined_anchors: dict = {}

        Reader.__init__(self, content)
        DottedAliasScanner.__init__(self)
        Parser.__init__(self)
        Composer.__init__(self)
        SafeConstructor.__init__(self)
        Resolver.__init__(self)

        # Reader derives a name from the stream; restore the real path so error
        # messages name the file instead of "<unicode string>".
        if name:
            self.name = name

    def compose_document(self):
        """Seed imported anchors per document and capture the locals.

        PyYAML clears ``self.anchors`` at the end of every document, so imported
        anchors must be re-seeded for each one and local anchors harvested
        before the reset. Locals correctly do not leak between documents, which
        matches YAML semantics, while imports are visible in all of them.
        """
        self.anchors.update(self._imported_anchors)

        self.get_event()  # DOCUMENT-START
        node = self.compose_node(None, None)
        self.get_event()  # DOCUMENT-END

        for key, anchor_node in self.anchors.items():
            # Identity, not name: an injected anchor is the same object we put in.
            if self._imported_anchors.get(key) is not anchor_node:
                self.defined_anchors[key] = anchor_node

        self.anchors = {}
        return node

    def exported_anchors(self) -> dict:
        """Anchors this file makes available to importers.

        Locally defined anchors are exported automatically. Imported anchors
        must be re-exported explicitly, and lose their prefix when they are, so
        ``#!export a.thing`` is aliased downstream as ``*<prefix>.thing``.
        """
        exported = dict(self.defined_anchors)
        origin: dict[str, str] = {name: "a local definition" for name in exported}

        for name in self._export_names:
            match = _EXPORT_NAME_RE.match(name)
            if not match:
                raise ExportError(f"invalid export name: {name!r}")
            prefix, local = match.groups()

            if local == "*":
                if prefix is None:
                    raise ExportError(
                        "'#!export *' is not valid; "
                        "local anchors are exported automatically"
                    )
                matched = {
                    key.split(".", 1)[1]: node
                    for key, node in self._imported_anchors.items()
                    if key.startswith(prefix + ".")
                }
                if not matched:
                    raise ExportError(
                        f"cannot export {name!r}: no anchors imported under "
                        f"prefix {prefix!r}"
                    )
                selected = matched
            elif prefix is None:
                if local not in self.defined_anchors:
                    raise ExportError(
                        f"cannot export unknown anchor {local!r}; "
                        f"this file defines: {sorted(self.defined_anchors) or 'none'}"
                    )
                continue  # already auto-exported
            else:
                key = f"{prefix}.{local}"
                if key not in self._imported_anchors:
                    raise ExportError(
                        f"cannot export unknown anchor {key!r}; "
                        f"available: {sorted(self._imported_anchors) or 'none'}"
                    )
                selected = {local: self._imported_anchors[key]}

            for out_name, node in selected.items():
                if out_name in exported and exported[out_name] is not node:
                    raise AnchorCollisionError(
                        f"export {name!r} would redefine {out_name!r}, "
                        f"already exported from {origin[out_name]}"
                    )
                exported[out_name] = node
                origin[out_name] = repr(name)

        return exported


def _resolve_imports(
    imports: list[Import],
    base_dir: str,
    importer: str | None,
    stack: list[str],
    cache: dict[str, dict],
) -> dict:
    """Load every import and merge their exports into one prefixed namespace."""
    anchors: dict = {}

    for directive in imports:
        target = os.path.normpath(os.path.join(base_dir, directive.path))
        sub_exports = _load_exports(target, importer, directive, stack, cache)

        for name, node in sub_exports.items():
            key = f"{directive.prefix}.{name}"
            if key in anchors and anchors[key] is not node:
                raise AnchorCollisionError(
                    f"anchor collision for {key!r}; two imports use prefix "
                    f"{directive.prefix!r}"
                )
            anchors[key] = node

    return anchors


def _load_exports(
    path: str,
    importer: str | None,
    directive: Import,
    stack: list[str],
    cache: dict[str, dict],
) -> dict:
    """Return the anchors *path* exports, composing it at most once."""
    real = os.path.realpath(path)

    if real in stack:
        chain = " -> ".join(stack + [real])
        raise CircularImportError(f"circular import detected: {chain}")

    if real in cache:
        return cache[real]

    where = f"{importer}, line {directive.line}" if importer else "the entry file"
    try:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
    except OSError as exc:
        raise ImportResolutionError(
            f"cannot import {directive.path!r} (from {where}): {exc.strerror}: {path}"
        ) from exc

    stack.append(real)
    try:
        loader = YamlIOLoader(text, name=path, _stack=stack, _cache=cache)
        try:
            # Compose only. An imported file's Python data is never used, only
            # its nodes, so constructing it would be wasted work. Subtrees that
            # are actually aliased get constructed by the root loader.
            while loader.check_node():
                loader.get_node()
            exports = loader.exported_anchors()
        finally:
            loader.dispose()
    finally:
        stack.pop()

    cache[real] = exports
    return exports


def load_imports_exports(file_path, processed=None):
    """Load *file_path*, returning ``(data, exported_anchors)``.

    Retained for backwards compatibility. Values in ``exported_anchors`` are
    ``yaml.Node`` objects, not constructed Python values. Prefer
    :func:`yaml_io.load`, which returns just the data.

    .. deprecated:: 0.2.0
    """
    stack: list[str] = []
    cache: dict[str, dict] = {}

    with open(file_path, "r", encoding="utf-8") as handle:
        text = handle.read()

    loader = YamlIOLoader(text, name=file_path, _stack=stack, _cache=cache)
    try:
        data = loader.get_single_data()
        return data, loader.exported_anchors()
    finally:
        loader.dispose()


__all__ = ["YamlIOLoader", "parse_directives", "load_imports_exports"]
