"""Entry point for `python -m scripts.ci_rca.evidence` -- packages need __main__.py (a bare
__init__.py cannot be `-m`-executed)."""

from scripts.ci_rca.evidence import main

if __name__ == "__main__":
    main()
