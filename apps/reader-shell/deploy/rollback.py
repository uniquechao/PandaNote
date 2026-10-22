#!/usr/bin/env python3
"""Default: inspect rollback plan. Explicit apply supports marked local clones only."""
import argparse
import json
from pathlib import Path
from install_support import InstallError, plan, rollback_clone


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=Path(__file__).with_name('install-plan.json'))
    parser.add_argument('--apply-clone', type=Path)
    args = parser.parse_args()
    try:
        manifest = json.loads(args.manifest.read_text())
        result = rollback_clone(args.apply_clone, manifest) if args.apply_clone else plan(manifest)
        print(json.dumps(result, indent=2))
    except (InstallError, OSError, ValueError) as e:
        parser.exit(1, str(e) + '\n')


if __name__ == '__main__':
    main()
