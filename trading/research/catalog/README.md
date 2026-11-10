# Strategy catalog and test engine, 2026-11-10

Working files of the full NQ strategy test. Results are not in yet; this folder holds what the tests are built from.

- `discovered.json`: 979 distinct NQ / Nasdaq-100 strategies found by the web search, with rules as published, sources and an evidence grade. `discovered_extra.json` adds one more (IV Walls).
- `TAXONOMY.md`: the 48 rule families the strategies were sorted into, each with its parameters and defaults.
- `assignments_all.json`: 1,077 assignments (some strategies have variants). 805 can be tested on price bars, 699 of them inside one trading day; 272 cannot (see `untestable.json` for the reason per strategy: discretion 92, not a strategy 61, needs tick data 40, needs other data 36, untrained model 22, needs intraday volume 21).
- `DATA_NOTES.md`: the 16 years of 1-minute bars and their limits. Rebuild them with `../code/fetch_histdata.py` and `../code/build_data.py`.
- `../engine/`: the shared backtest engine (`engine.py`, guide in `ENGINE.md`) with its 113 unit tests and the 49 tests of an independent review. The review found and fixed two defects (a lookahead check that missed one-bar leaks, and bar times for bar lengths that do not divide a day); fills, costs, session rules and statistics held up.

The engine files expect the data under the session scratchpad path they were written with; change `DATA_DIR` in `engine.py` after rebuilding the data elsewhere.
