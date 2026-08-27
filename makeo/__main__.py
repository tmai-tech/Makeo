"""python -m makeo enqueue ...  (also python -m makeo.enqueue)."""

import sys

from makeo.enqueue import main

if __name__ == "__main__":
    # allow `python -m makeo enqueue --brand buzzit`
    if len(sys.argv) > 1 and sys.argv[1] == "enqueue":
        sys.argv.pop(1)
    main()
