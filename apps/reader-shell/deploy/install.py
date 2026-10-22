#!/usr/bin/env python3
"""Print the reviewed plan by default; explicit apply supports local clones only."""
import argparse
import json
from pathlib import Path
from install_support import InstallError, apply_clone, plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=Path(__file__).with_name('install-plan.json'))
    parser.add_argument('--apply-clone', type=Path)
    parser.add_argument('--bundle', type=Path)
    args = parser.parse_args()
    try:
        manifest = json.loads(args.manifest.read_text())
        if args.apply_clone:
            if not args.bundle:
                parser.error('--bundle required with --apply-clone')
            result = apply_clone(args.apply_clone, args.bundle, manifest)
        else:
            result = plan(manifest)
        print(json.dumps(result, indent=2))
    except (InstallError, OSError, ValueError) as e:
        parser.exit(1, str(e) + '\n')


if __name__ == '__main__':
    main()
