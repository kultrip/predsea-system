# Processing

NetCDF-to-JSON translation and captain-ready model interpretation live here.

Phase 4 includes `mariner_interpreter.py`. It currently uses `xarray` against a
real `wrfout_d03` fixture and returns captain-ready JSON for an LLM agent.

Run:

```bash
python processing/run_phase4_summary.py
```

Route sampling is also available:

```bash
python processing/run_route_summary.py
```

Dijkstra lowest-wind routing is available:

```bash
python processing/run_optimal_route.py
```

Multi-domain route comparison is available for the d01, d02, and d03 samples:

```bash
python processing/run_route_comparison.py
```
