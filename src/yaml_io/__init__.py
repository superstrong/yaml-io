import os
import yaml
from .loader import load_imports_exports

# stash originals to avoid recursion
_yaml_safe_load = yaml.safe_load
_yaml_load = yaml.load

def safe_load(stream_or_path):
    # file path?
    if isinstance(stream_or_path, str) and os.path.exists(stream_or_path):
        data, _ = load_imports_exports(stream_or_path)
        return data

    # file-like?
    if hasattr(stream_or_path, "read"):
        name = getattr(stream_or_path, "name", None)
        if name and os.path.exists(name):
            data, _ = load_imports_exports(name)
            return data
        # fallback: read in-memory
        txt = stream_or_path.read()
        return _yaml_safe_load(txt)

    # anything else (string snippet, etc.)
    return _yaml_safe_load(stream_or_path)

# override the global hooks
yaml.safe_load = safe_load
yaml.load = safe_load

__all__ = ["load_imports_exports", "safe_load"]
