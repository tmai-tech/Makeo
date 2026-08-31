"""Operator-provision a user.

    MAKEO_MASTER_KEY=... python -m makeo.create_user you@brand.com 'password' ['Ada']
"""

import sys

from app.main import create_user


def main(argv=None):
    argv = argv or sys.argv[1:]
    if len(argv) not in (2, 3):
        sys.exit("usage: python -m makeo.create_user EMAIL PASSWORD [NAME]")
    name = argv[2] if len(argv) == 3 else ""
    uid = create_user(argv[0], argv[1], name)
    print(f"created {argv[0]} id={uid}")


if __name__ == "__main__":
    main()
