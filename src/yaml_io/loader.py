import os
import re
import yaml

# We subclass the yaml.SafeLoader so we can customize anchor handling.
class ImportExportYAMLLoader(yaml.SafeLoader):
    pass

def _parse_directives(content):
    """
    Scan the YAML content for custom directives and remove them.
    
    Directives:
    - "#!import <path> as <prefix>" to import anchors from another file.
    - "#!export ..." to explicitly export imported anchors.
    
    Return the cleaned content, a list of import directives, and a list of explicit exports.
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

def load_imports_exports(file_path, processed_files=None):
    """
    Load a YAML file with custom import and export directives.
    
    Anchors defined in this file are automatically available downstream.
    Imported anchors must be re‑exported explicitly to be passed along.
    
    This recursively loads imported files to gather their exported anchors, prefix them,
    and inject them into the loader before loading the YAML content.
    
    Returns a tuple (data, exported_anchors) where 'data' is the YAML content and 
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
    
    # Remove directives from the content and capture them.
    content, import_directives, explicit_exports = _parse_directives(content)
    
    # Gather imported anchors from each import directive.
    imported_anchors = {}
    for directive in import_directives:
        import_path = os.path.join(os.path.dirname(file_path), directive['path'])
        # Recursively load the imported file to get its exported anchors.
        _, exported = load_imports_exports(import_path, processed_files)
        # Add each imported anchor with the given prefix.
        for anchor, value in exported.items():
            new_anchor = f"{directive['prefix']}.{anchor}"
            # If new_anchor already exists but points to a different object => collision
            if new_anchor in imported_anchors and imported_anchors[new_anchor] is not value:
                raise ValueError(
                    f"Anchor collision for '{new_anchor}' imported multiple times from different sources."
                )
            imported_anchors[new_anchor] = value

    # Create a custom loader and inject the imported anchors.
    loader = ImportExportYAMLLoader(content)
    if not hasattr(loader, 'anchors'):
        loader.anchors = {}
    loader.anchors.update(imported_anchors)
    
    # Load the YAML content into a Python object.
    data = loader.get_single_data()
    
    # Determine which anchors were defined locally in this file.
    local_anchors = {k: v for k, v in loader.anchors.items() if k not in imported_anchors}
    
    # Prepare the final export dictionary.
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
            # If the export directive has no dot, assume it's a local anchor.
            if exp in loader.anchors:
                exported_anchors[exp] = loader.anchors[exp]
    
    return data, exported_anchors
