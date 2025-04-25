import os
import re
import io
import yaml
from yaml.reader import Reader
from yaml.scanner import Scanner, ScannerError
from yaml.parser import Parser
from yaml.composer import Composer
from yaml.constructor import SafeConstructor
from yaml.resolver import Resolver

###
# Monkey-patch the Scanner so that aliases can include exactly one dot.
###
def custom_scan_anchor(self, TokenClass):
    start_mark = self.get_mark()
    marker     = self.peek()
    if marker not in ("&", "*"):
        raise ScannerError(
            "while scanning an anchor/alias", start_mark,
            f"expected '&' or '*', but found {marker!r}", self.get_mark()
        )
    self.forward()  # consume the & or *

    terminators = " \t\r\n,[]{}"
    # --- definition (&)
    if marker == "&":
        name_chars = []
        ch = self.peek()
        if not (ch.isalnum() or ch == "_"):
            raise ScannerError(
                "while scanning an anchor", start_mark,
                f"expected alnum or '_', but found {ch!r}", self.get_mark()
            )
        while True:
            ch = self.peek()
            if not ch or ch in terminators:
                break
            if ch == ".":
                raise ScannerError(
                    "while scanning an anchor", start_mark,
                    "periods not allowed in anchor names", self.get_mark()
                )
            if ch.isalnum() or ch in ("_", "-"):
                name_chars.append(ch)
                self.forward()
            else:
                break
        return TokenClass("".join(name_chars), start_mark, self.get_mark())

    # --- alias (*)
    alias_chars = []
    dot_seen    = False
    ch = self.peek()
    if not (ch.isalnum() or ch == "_"):
        raise ScannerError(
            "while scanning an alias", start_mark,
            f"expected alnum or '_', but found {ch!r}", self.get_mark()
        )
    while True:
        ch = self.peek()
        if not ch or ch in terminators:
            break
        if ch == ".":
            if dot_seen:
                raise ScannerError(
                    "while scanning an alias", start_mark,
                    "only one period allowed in an imported alias", self.get_mark()
                )
            dot_seen = True
            alias_chars.append(ch)
            self.forward()
            continue
        if ch.isalnum() or ch in ("_", "-"):
            alias_chars.append(ch)
            self.forward()
            continue
        break

    alias = "".join(alias_chars)
    if dot_seen:
        if alias.startswith(".") or alias.endswith(".") or alias.count(".") != 1:
            raise ScannerError(
                "while scanning an alias", start_mark,
                f"invalid imported alias format: {alias}", self.get_mark()
            )
    return TokenClass(alias, start_mark, self.get_mark())

# apply the patch
Scanner.scan_anchor = custom_scan_anchor

###
# Build a proper SafeLoader subclass that wires up Reader→Scanner→Parser→Composer→Constructor→Resolver
###
class ImportExportYAMLLoader(
    Reader, Scanner, Parser, Composer, SafeConstructor, Resolver
):
    def __init__(self, stream):
        Reader.__init__(self, stream)
        Scanner.__init__(self)
        Parser.__init__(self)
        Composer.__init__(self)
        SafeConstructor.__init__(self)
        Resolver.__init__(self)


_import_re  = re.compile(r"^#!import\s+(.+?)\s+as\s+(\w+)")
_export_re  = re.compile(r"^#!export\s+(.+)")
def _parse_directives(text):
    lines = text.splitlines()
    kept, imports, exports = [], [], []
    for L in lines:
        m = _import_re.match(L)
        if m:
            imports.append({"path": m.group(1).strip(), "prefix": m.group(2).strip()})
            continue
        m = _export_re.match(L)
        if m:
            exports.extend([a.strip() for a in m.group(1).split(",")])
            continue
        kept.append(L)
    return "\n".join(kept), imports, exports

def load_imports_exports(file_path, processed=None):
    """
    Returns (data_obj, exported_anchors_dict)
    """
    if processed is None:
        processed = set()
    absp = os.path.abspath(file_path)
    if absp in processed:
        raise ValueError(f"Circular import detected: {file_path}")
    processed.add(absp)

    raw = open(file_path, "r", encoding="utf-8").read()
    content, imports, exports = _parse_directives(raw)

    # recursively load all anchors from imports
    imported_anchors = {}
    for d in imports:
        impath = os.path.join(os.path.dirname(file_path), d["path"])
        _, sub_exported = load_imports_exports(impath, processed)
        for name, node in sub_exported.items():
            pref = f"{d['prefix']}.{name}"
            if pref in imported_anchors and imported_anchors[pref] is not node:
                raise ValueError(f"Anchor collision for '{pref}'")
            imported_anchors[pref] = node

    # run the actual loader
    stream = io.StringIO(content)
    loader = ImportExportYAMLLoader(stream)
    # inject all imported anchors *before* parsing
    loader.anchors.update(imported_anchors)

    # explicit parse → construct
    root_node = loader.get_single_node()
    data     = loader.construct_document(root_node)

    # figure out what this file defines locally
    local = {
        k: v
        for k, v in loader.anchors.items()
        if k not in imported_anchors
    }

    # everything in `local` is auto-exported; imported anchors must be explicitly re-exported
    exported = dict(local)
    for e in exports:
        if "." in e:
            pfx, nm = e.split(".", 1)
            key = f"{pfx}.{nm}"
            if key in loader.anchors:
                exported[nm] = loader.anchors[key]
        else:
            if e in loader.anchors:
                exported[e] = loader.anchors[e]

    return data, exported
