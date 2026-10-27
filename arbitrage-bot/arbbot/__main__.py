"""``python -m arbbot ...`` is the same as the ``arbbot`` console script."""

from .cli import main

raise SystemExit(main())
