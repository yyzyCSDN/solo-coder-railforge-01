# RailForge Public Benchmark

A dependency-free freight railway operations benchmark with a public smoke suite. Private task prompts, hidden regressions and broken snapshots are deliberately excluded from this package.

## Cross-bureau path coordination

`railforge.coordination` coordinates freight train paths across railway
bureaus. `coordinate()` / `batch_coordinate()` generate departure-shift
candidates from customer time windows, per-section hourly capacity, block
occupancies (with headway guards) and train priority, returning a `Decision`
that is either an accepted `CandidatePath` or an explainable `Rejection`
(`SINGLE_TRACK_MEET`, `SECTION_CAPACITY`, `BLOCK_OCCUPIED`, `WINDOW_MISSED`,
`STALE_VERSION`, `UNKNOWN_SECTION`).

Accepted paths are committed through `RailForgeService.coordinate_freight_path`
as one atomic unit: versioned plan row, hash-chained cursor event, audit record
and section occupancy in the optimistic-concurrency `PathLedger`. Any failed
write rolls the whole unit back, a stale `expected_version` is refused before
sections are examined, and replaying the same request never occupies a section
twice. Run the layered suite with:

```
PYTHONPATH=src python3 -m unittest discover -s tests
```
