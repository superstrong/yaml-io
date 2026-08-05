"""Load both example workspaces and show what the indirection buys you.

    python examples/show.py

acme and globex are byte-identical except for which package they import.
That one line is the difference between v1.2 and v1.3 policy values.
"""

import json
import sys
from pathlib import Path

import yaml_io

HERE = Path(__file__).parent


def main() -> int:
    resolved = {}

    for workspace in ("acme", "globex"):
        path = HERE / "workspaces" / workspace / "actions.yml"
        data = yaml_io.load(path)
        resolved[workspace] = data

        package = "prod-default (v1.2)" if workspace == "acme" else "prod-beta (v1.3)"
        print(f"=== {workspace} via {package} ===")
        print(json.dumps(data, indent=2))
        print()

    acme_retry = resolved["acme"]["jobs"][0]["retry"]
    globex_retry = resolved["globex"]["jobs"][0]["retry"]

    print("Same alias, *base.retry_policy, resolved in each workspace:")
    print(f"  acme   -> {acme_retry}")
    print(f"  globex -> {globex_retry}")
    print()

    # The router file itself is nothing but directives, so it has no data.
    package = yaml_io.load(HERE / "packages" / "prod-default.yml")
    print(f"prod-default.yml is directives only, so it loads as: {package!r}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
