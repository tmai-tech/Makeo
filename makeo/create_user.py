"""Operator-provision a waitlisted user.

    MAKEO_MASTER_KEY=... python -m makeo.create_user you@brand.com 'password'
"""

import sys

from app.main import create_user


def main(argv=None):
    argv = argv or sys.argv[1:]
    if len(argv) != 2:
        sys.exit("usage: python -m makeo.create_user EMAIL PASSWORD")
    uid = create_user(argv[0], argv[1])
    print(f"created {argv[0]} id={uid}")


if __name__ == "__main__":
    main()
