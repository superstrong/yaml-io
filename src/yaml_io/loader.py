import os
import re
import yaml
from yaml.scanner import Scanner, ScannerError
from yaml.tokens import AliasToken

# --- Custom Scanner Patch ---
def custom_scan_anchor(self, TokenClass):
    """
    Custom scan_anchor for PyYAML's Scanner.

    - When the token starts with '&', we scan an anchor name using the default allowed characters,
      rejecting any period ('.') because periods are reserved.
    - When the token starts with '*', we scan an alias name, allowing exactly one period to serve
      as the separator between the import prefix and the anchor name.
    The token is terminated by whitespace or YAML punctuation.
    """
    start_mark = self.get_mark()
    marker = self.peek()  # should be either '&' or '*'
    if marker not in ('&', '*'):
        raise ScannerError("while scanning an anchor/alias", start_mark,
                             f"expected '&' or '*', but found {marker!r}", self.get_mark())
    self.forward()  # consume the marker

    # Define termination characters (this list is a simplified approximation).
    terminators = ' \t\r\n,[]{}'

    # --- Anchor definition: marker '&'
    if marker == '&':
        anchor_chars = []
        ch = self.peek()
        if not (ch.isalnum() or ch == '_'):
            raise ScannerError("while scanning an anchor", start_mark,
                                 f"expected alphabetic or numeric character, but found {ch!r}", self.get_mark())
        while True:
            ch = self.peek()
            if not ch or ch in terminators:
                break
            # Do not allow a period in an anchor definition.
            if ch == '.':
                raise ScannerError("while scanning an anchor", start_mark,
                                     f"period not allowed in anchor names: {ch!r}", self.get_mark())
            if ch.isalnum() or ch in ['_', '-']:
                anchor_chars.append(ch)
                self.forward()
            else:
                break
        anchor_name = ''.join(anchor_chars)
        return TokenClass(anchor_name, start_mark, self.get_mark())

    # --- Alias: marker '*'
    else:
        alias_chars = []
        dot_seen = False
        ch = self.peek()
        if not (ch.isalnum() or ch == '_'):
            raise ScannerError("while scanning an alias", start_mark,
                                 f"expected alphabetic or numeric character, but found {ch!r}", self.get_mark())
        while True:
            ch = self.peek()
            if not ch or ch in terminators:
                break
            if ch == '.':
                if dot_seen:
                    # If a second period is found, stop scanning here.
                    break
                dot_seen = True
                alias_chars.append(ch)
                self.forward()
                continue
            if ch.isalnum() or ch == '_':
                alias_chars.append(ch)
                self.forward()
            else:
                break
        alias_name = ''.join(alias_chars)
        if dot_seen:
            # Ensure the period is not at the start or end and occurs exactly once.
            if alias_name.startswith('.') or alias_name.endswith('.') or alias_name.count('.') != 1:
                raise ScannerError("while scanning an alias", start_mark,
                                     f"invalid alias format with period: {alias_name}", self.get_mark())
        return TokenClass(alias_name, start_mark, self.get_mark())

# Monkey-patch PyYAML's Scanner to use our custom scan_anchor.
Scanner.scan_anchor = custom_scan_anchor

# --- Custom Loader ---
# Subclass yaml.SafeLoader so we can inject imported anchors.
class ImportExportYAMLLoader(yaml.SafeLoader):
    pass

# --- Directive Parsing ---
def _parse_directives(content):
    """
    Scan the YAML content for custom directives and remove them.
    
    Directives:
      - "#!import <path> as <prefix>" to import anchors from another file.
      - "#!export ..." to explicitly export imported anchors.
    
    Returns:
      - The cleaned YAML content (with directives removed)
      - A list of import directives (each a dict with 'path' and 'prefix')
      - A list of explicit export strings.
    """
    lines = content.splitlines()
    processed_lines = []
    import_directives = []
    export_directives = []
    import_re = re.compile(r"^#!import\s+(.+?)\s+as\s+(\w+)")
    export_re = re.compile(r"^#!export\s+(.+)")
    for line in lines:
        import_match = import_re.match(line)
        if import_match:
            path = import_match.group(1).strip()
            prefix = import_match.group(2).strip()
            import_directives.append({'path': path, 'prefix': prefix})
            continue
        export_match = export_re.match(line)
        if export_match:
            anchors_str = export_match.group(1).strip()
            anchors = [a.strip() for a in anchors_str.split(",")]
            export_directives.extend(anchors)
            continue
        processed_lines.append(line)
    return "\n".join(processed_lines), import_directives, export_directives

# --- Main Functionality ---
def load_imports_exports(file_path, processed_files=None):
    """
    Load a YAML file with custom import and export directives.
    
    Anchors defined in this file are automatically available downstream.
    Imported anchors must be re‑exported explicitly to be passed along.
    
    This recursively loads imported files to gather their exported anchors,
    prefixes them (using a period as a separator), and injects them into the loader
    before loading the YAML content.
    
    Returns:
      A tuple (data, exported_anchors) where 'data' is the parsed YAML data and 
      'exported_anchors' is a dict of anchors that this file passes downstream.
    """
    if processed_files is None:
        processed_files = set()
    abs_path = os.path.abspath(file_path)
    if abs_path in processed_files:
        raise ValueError(f"Circular import detected for file: {file_path}")
    processed_files.add(abs_path)

    with open(file_path, "r") as f:
        content = f.read()

    # Remove custom directives and capture import/export instructions.
    content, import_directives, explicit_exports = _parse_directives(content)

    # --- Process Imported Anchors ---
    imported_anchors = {}
    for directive in import_directives:
        import_path = os.path.join(os.path.dirname(file_path), directive['path'])
        # Recursively load the imported file to get its exported anchors.
        _, exported = load_imports_exports(import_path, processed_files)
        # Prefix each exported anchor with the directive's prefix using a period.
        for anchor, value in exported.items():
            new_anchor = f"{directive['prefix']}.{anchor}"
            if new_anchor in imported_anchors and imported_anchors[new_anchor] is not value:
                raise ValueError(
                    f"Anchor collision for '{new_anchor}' imported multiple times from different sources."
                )
            imported_anchors[new_anchor] = value

    # --- Create Loader and Inject Imported Anchors ---
    loader = ImportExportYAMLLoader(content)
    if not hasattr(loader, 'anchors'):
        loader.anchors = {}
    loader.anchors.update(imported_anchors)

    # Load the YAML content.
    data = loader.get_single_data()

    # Determine which anchors were defined locally (i.e. not imported).
    local_anchors = {k: v for k, v in loader.anchors.items() if k not in imported_anchors}

    # --- Prepare Exported Anchors ---
    # Local anchors are automatically exported.
    exported_anchors = {}
    exported_anchors.update(local_anchors)
    # Imported anchors must be re‑exported explicitly.
    for exp in explicit_exports:
        if '.' in exp:
            prefix, anchor_name = exp.split('.', 1)
            full_anchor = f"{prefix}.{anchor_name}"
            if full_anchor in loader.anchors:
                # Export the imported anchor under the unprefixed name.
                exported_anchors[anchor_name] = loader.anchors[full_anchor]
        else:
            # Assume a non-prefixed export directive refers to a local anchor.
            if exp in loader.anchors:
                exported_anchors[exp] = loader.anchors[exp]

    return data, exported_anchors
