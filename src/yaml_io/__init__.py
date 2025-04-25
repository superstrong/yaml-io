import os
import yaml
from .loader import load_imports_exports

def safe_load(path_or_stream):
    # If user passed a filepath, resolve imports first
    if isinstance(path_or_stream, str) and os.path.exists(path_or_stream):
        data, _ = load_imports_exports(path_or_stream)
        return data

    # If it's a file-like with a name, do the same
    reader = getattr(path_or_stream, "read", None)
    if reader and hasattr(path_or_stream, "name") and os.path.exists(path_or_stream.name):
        data, _ = load_imports_exports(path_or_stream.name)
        return data

    # Otherwise defer to normal PyYAML
    return yaml.safe_load(path_or_stream)

# Override PyYAML hooks
yaml.safe_load = safe_load
yaml.load      = safe_load