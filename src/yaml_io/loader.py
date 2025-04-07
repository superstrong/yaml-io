import os
import re
import yaml
from yaml.scanner import Scanner, ScannerError
from yaml.tokens import AliasToken

# Custom scanner patch
def custom_scan_anchor(self, TokenClass):
    """
    Custom scan_anchor method for PyYAML's scanner.
    
    This implementation allows a single period ('.') only if it acts as a separator
    between an import prefix and an alias name. In other cases, a period is not allowed.
    """
    start_mark = self.get_mark()

    # The first character must be alphanumeric or underscore.
    ch = self.peek()
    if not (ch.isalnum() or ch == '_'):
        raise ScannerError("while scanning an alias", start_mark,
                             f"expected alphabetic or numeric character, but found {ch!r}", self.get_mark())

    alias_chars = []
    dot_seen = False
    while True:
        ch = self.peek()
        if not ch:
            break

        # Allow a period only if one has not yet been seen.
        if ch == '.':
            if dot_seen:
                # A second period is not allowed; break so the token ends here.
                break
            dot_seen = True
            alias_chars.append(ch)
            self.forward()  # Consume the period
            continue

        # Allow alphanumeric and underscore characters.
        if ch.isalnum() or ch == '_':
            alias_chars.append(ch)
            self.forward()
        else:
            # Stop scanning when a non-valid character is encountered.
            break

    alias_name = ''.join(alias_chars)

    # If a period was seen, ensure it is not at the beginning or end and occurs exactly once.
    if dot_seen:
        if alias_name.startswith('.') or alias_name.endswith('.') or alias_name.count('.') != 1:
            raise ScannerError("while scanning an alias", start_mark,
                                 f"invalid alias format with period: {alias_name}", self.get_mark())

    return TokenClass(alias_name, start_mark, self.get_mark())

# Patch the PyYAML Scanner for the loader
Scanner.scan_anchor = custom_scan_anchor

# We subclass yaml.SafeLoader so we can inject imported anchors.
class ImportExportYAMLLoader(yaml.SafeLoader):
    pass

# Directive Parsing
def _parse_directives(content):
    """
    Scan the YAML content for custom directives and remove them.
    
    Directives:
    - "#!import <path> as <prefix>" to import anchors from another file.
    - "#!export ..." to explicitly export imported anchors.
    
    Returns:
      - cleaned YAML content (with directives removed)
      - a list of import directives (each a dict with 'path' and 'prefix')
      - a list of explicit export strings.
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

# Main functions
def load_imports_exports(file_path, processed_files=None):
    """
    Load a YAML file with custom import and export directives.
    
    Anchors defined in this file are automatically available downstream.
    Imported anchors must be re‑exported explicitly to be passed along.
    
    This recursively loads imported files to gather their exported anchors, prefixes them
    (using a period as a separator), and injects them into the loader before loading the YAML content.
    
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

    # Process Imported Anchors
    imported_anchors = {}
    for directive in import_directives:
        import_path = os.path.join(os.path.dirname(file_path), directive['path'])
        # Recursively load the imported file to get its exported anchors.
        _, exported = load_imports_exports(import_path, processed_files)
        # Prefix each exported anchor with the directive's prefix using a period as a separator.
        for anchor, value in exported.items():
            new_anchor = f"{directive['prefix']}.{anchor}"
            if new_anchor in imported_anchors and imported_anchors[new_anchor] is not value:
                raise ValueError(
                    f"Anchor collision for '{new_anchor}' imported multiple times from different sources."
                )
            imported_anchors[new_anchor] = value

    # Create Loader and Inject Imported Anchors
    loader = ImportExportYAMLLoader(content)
    if not hasattr(loader, 'anchors'):
        loader.anchors = {}
    loader.anchors.update(imported_anchors)

    # Load the YAML content.
    data = loader.get_single_data()

    # Determine which anchors were defined locally (i.e. not imported).
    local_anchors = {k: v for k, v in loader.anchors.items() if k not in imported_anchors}

    # Prepare Exported Anchors
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
