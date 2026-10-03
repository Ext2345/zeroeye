# Monitoring setup tests

Run the standard-library regression tests from the repository root:

```sh
python -m unittest discover -s tests -v
```

The PromQL threshold and pending-duration evaluation runs when `promtool` is on
`PATH`. To use a specific binary, set `PROMTOOL` to its executable path before
running unittest. Without either, that evaluation test is skipped; the other
tests need only Python's standard library and no monitoring services or
credentials.

The memory ratio rule expects `process_resident_memory_bytes` and
`machine_memory_bytes` to carry matching Prometheus labels (including the
instance identity), so vector matching pairs each process with its host total.
`machine_memory_bytes` must report the host's total memory and be nonzero. If
that metric is absent for a series, Prometheus produces no ratio for it and the
alert does not fire for that series.
