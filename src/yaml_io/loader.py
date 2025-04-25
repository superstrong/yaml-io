import os
import re
import io
import yaml
from yaml.scanner import Scanner, ScannerError
from yaml.tokens import AliasToken

# --- Custom Scanner Patch ---
# Override PyYAML's anchor scanning to support external imports (prefix.anchor)
def custom_scan_anchor(self, TokenClass):
    start_mark = self.get_mark()
    marker = self.peek()
    if marker not in ('&', '*'):
        raise ScannerError(
            "while scanning an anchor/alias", start_mark,
            f"expected '&' or '*', but found {marker!r}", self.get_mark()
        )
    self.forward()  # consume '&' or '*'

    terminators = ' \t\r\n,[]{}'

    # --- Anchor definition (&)
    if marker == '&':
        anchor_chars = []
        ch = self.peek()
        if not (ch.isalnum() or ch == '_'):
            raise ScannerError(
                "while scanning an anchor", start_mark,
                f"expected alnum or '_', but found {ch!r}", self.get_mark()
            )
        while True:
            ch = self.peek()
            if not ch or ch in terminators:
                break
            if ch == '.':
                raise ScannerError(
                    "while scanning an anchor", start_mark,
                    "period not allowed in anchor names", self.get_mark()
                )
            if ch.isalnum() or ch in ['_', '-']:
                anchor_chars.append(ch)
                self.forward()
            else:
                break
        return TokenClass(''.join(anchor_chars), start_mark, self.get_mark())

    # --- Alias reference (*)
    alias_chars = []
    dot_seen = False
    ch = self.peek()
    if not (ch.isalnum() or ch == '_'):
        raise ScannerError(
            "while scanning an alias", start_mark,
            f"expected alnum or '_', but found {ch!r}", self.get_mark()
        )
    while True:
        ch = self.peek()
        if not ch or ch in terminators:
            break
        if ch == '.':
            if dot_seen:
                raise ScannerError(
                    "while scanning an alias", start_mark,
                    "multiple periods not allowed in alias names", self.get_mark()
                )
            dot_seen = True
            alias_chars.append(ch)
            self.forward()
            continue
        if ch.isalnum() or ch in ['_', '-']:
            alias_chars.append(ch)
            self.forward()
            continue
        break
    alias_name = ''.join(alias_chars)
    # ensure exactly one period if dot seen
    if dot_seen:
        if alias_name.startswith('.') or alias_name.endswith('.') or alias_name.count('.') != 1:
            raise ScannerError(
                "while scanning an alias", start_mark,
                f"invalid alias format: {alias_name}", self.get_mark()
            )
    return TokenClass(alias_name, start_mark, self.get_mark())

# Apply the patch globally
Scanner.scan_anchor = custom_scan_anchor

# --- Custom Loader ---
class ImportExportYAMLLoader(yaml.SafeLoader):
    """YAML loader that supports import/export of anchors across files."""
    pass

# --- Directive Parsing ---
_directive_import = re.compile(r'^#!import\s+(.+?)\s+as\s+(\w+)', re.MULTILINE)
_directive_export = re.compile(r'^#!export\s+(.+)', re.MULTILINE)

def _parse_directives(content):
    lines = content.splitlines()
    processed, imports, exports = [], [], []
    for line in lines:
        m = _directive_import.match(line)
        if m:
            imports.append({'path': m.group(1).strip(), 'prefix': m.group(2).strip()})
            continue
        m = _directive_export.match(line)
        if m:
            exports.extend([a.strip() for a in m.group(1).split(',')])
            continue
        processed.append(line)
    return "\n".join(processed), imports, exports

# --- Main Functionality ---
def load_imports_exports(file_path, processed_files=None):
    if processed_files is None:
        processed_files = set()

    abs_path = os.path.abspath(file_path)
    if abs_path in processed_files:
        raise ValueError(f"Circular import detected: {file_path}")
    processed_files.add(abs_path)

    raw = open(file_path, 'r', encoding='utf-8').read()
    content, import_dirs, explicit_exports = _parse_directives(raw)

    # Recursively load imports
    imported_anchors = {}
    for d in import_dirs:
        ip = os.path.join(os.path.dirname(file_path), d['path'])
        _, exported = load_imports_exports(ip, processed_files)
        for name, val in exported.items():
            prefixed = f"{d['prefix']}.{name}"
            if prefixed in imported_anchors and imported_anchors[prefixed] is not val:
                raise ValueError(f"Anchor collision for '{prefixed}' from '{ip}'")
            imported_anchors[prefixed] = val

    # Initialize loader with content
    loader = ImportExportYAMLLoader(io.StringIO(content))
    # Inject imported anchors
    loader.anchors.update(imported_anchors)

    # Parse the YAML data
    data = loader.get_single_data()

    # Identify local anchors (excluding imported)
    local_anchors = {k: v for k, v in loader.anchors.items() if k not in imported_anchors}

    # Prepare export dict
    exported_anchors = local_anchors.copy()
    for exp in explicit_exports:
        if '.' in exp:
            pre, anchor = exp.split('.', 1)
            key = f"{pre}.{anchor}"
            if key in loader.anchors:
                exported_anchors[anchor] = loader.anchors[key]
        else:
            if exp in loader.anchors:
                exported_anchors[exp] = loader.anchors[exp]

    return data, exported_anchors
