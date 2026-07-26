---
title: "PredSea: A Scalable Cloud-Native Oceanographic Forecasting System"
subtitle: "1 km High-Resolution Coastal Intelligence & Operational Decision Framework"
author: "PredSea Oceanographic Research & Engineering Group"
date: "July 2026"
status: "Operational / Technical Reference"
abstract: |
  Traditional coastal oceanography and wave dynamics modeling rely on dedicated high-performance computing (HPC) clusters or monolithic, expensive cloud runners. These legacy paradigms suffer from rigid resource allocation, high capital expenditure, and slow multi-domain scheduling.
  
  PredSea introduces a serverless, cloud-native oceanographic forecasting architecture that replaces fixed HPC infrastructure with dynamically orchestrated Google Cloud Platform (GCP) Batch compute, Spot Virtual Machines, MPI-parallelized numerical engines (CROCO, SWAN, WRF), and GIL-bypassing parallel Python pre-processors.
  
  By coupling high-resolution Weather Research and Forecasting (WRF) atmospheric driving fields (1 km grid resolution) with CROCO and SWAN, PredSea resolves fine-scale coastal bathymetry, island wind shadows, and thermal boundary dynamics across five major Western Mediterranean sectors in under 45 minutes at an operational cost of ~$2.22 per daily cycle.
---

# Executive Summary & Core Positioning

## 1. The Operational Problem: Coarse Grids Miss Coastal Physics
Global physical products—such as those from ECMWF and Copernicus Marine Environment Monitoring Service (CMEMS)—provide essential ocean-state baselines at $4.2\text{ km}$ to $25\text{ km}$ horizontal resolutions. However, coarse global grids smooth out critical coastal bathymetric features, flatten narrow island channels (e.g., Freus channel between Ibiza and Formentera, Dragonera channel off Mallorca), and underestimate wave-current interactions and local wind-sea generation.

## 2. The Commercial & Coastal Value of 1 km Resolution
PredSea bridges this operational gap with an explicit positioning philosophy:

> **Ocean data is everywhere. Operational decisions are not.**

By downscaling regional ocean state data onto a high-resolution **$1\text{ km}$ curvilinear grid** ($401 \times 501$ nodes across 32 vertical $\sigma$-layers in the Balearic Basin), PredSea provides:
* **Sub-Kilometer Coastal Accuracy:** Resolves steep shoreline bathymetry, narrow island channels, and localized coastal upwelling anomalies.
* **Predictive Decision Intelligence:** Converts raw 3D velocity vectors and wave spectra into vessel response metrics, port safety alerts, and captain-facing advice.
* **Unmatched Unit Economics:** Delivers regional scale high-resolution forecasts at ~$2.22/day using serverless GCP Batch Spot execution—a >90% reduction compared to legacy HPC infrastructure.

```
+-----------------------------------------------------------------------------------+
|                                 PredSea Platform                                  |
|                                                                                   |
|  +--------------------+    +--------------------+    +-------------------------+  |
|  |   WRF Atmosphere   |    |    SWAN Waves      |    |       CROCO Ocean       |  |
|  |  (10m Wind, Flux)  |    | (Hs, Tp, Spectrum) |    |  (3D u, v, T, S, Zeta)  |  |
|  +---------+----------+    +---------+----------+    +------------+------------+  |
|            |                         |                            |               |
|            +-------------------------+----------------------------+               |
|                                      |                                            |
|                                      v                                            |
|                  +---------------------------------------+                        |
|                  |      GCP Batch Spot Execution         |                        |
|                  +-------------------+-------------------+                        |
|                                      |                                            |
|                                      v                                            |
|                  +---------------------------------------+                        |
|                  |    Canonical NetCDF4 + GCS Pipeline   |                        |
|                  +-------------------+-------------------+                        |
|                                      |                                            |
|                                      v                                            |
|                  +---------------------------------------+                        |
|                  | BigQuery Decision Engine & REST APIs  |                        |
|                  +---------------------------------------+                        |
+-----------------------------------------------------------------------------------+
```

---

## Key Performance Indicators (KPIs)

| Parameter | Legacy Cluster Model | PredSea Cloud-Native Architecture |
| :--- | :--- | :--- |
| **Execution Paradigm** | Fixed On-Prem / Monolithic VM | **Serverless GCP Batch Spot Instances** |
| **Grid Resolution** | $4.2\text{ km} - 10\text{ km}$ (Global/Regional) | **$1.0\text{ km}$ (High-Resolution Coastal Tiles)** |
| **Pre-Processing Time** | 40 minutes (Single-threaded) | **1 min 42 sec** (Python `ProcessPoolExecutor`) |
| **Total Western Med Compute Time** | > 28 Hours (Sequential) | **< 35 Minutes** (Parallel Region Spot Execution) |
| **Daily Infrastructure Cost** | ~$45.00 / day | **~$2.22 / day** (Spot VM + GCS + BigQuery) |
| **Validation Benchmark** | $H_s \text{ RMSE} \approx 0.42\text{ m}$ | **$H_s \text{ RMSE} \le 0.11\text{ m}$** (SOCIB Buoy Ground Truth) |

---

## Table of Contents

The complete technical specification is structured across six dedicated sub-documents:

1. [**01_system_architecture.md**](./01_system_architecture.md)  
   *End-to-end Data Pipeline: Upstream ECMWF/CMEMS ingestion, Python GIL-bypass pre-processing, bulk forcing compilation (`croco_blk.nc`, `croco_bry.nc`, `croco_ini.nc`), and GCS cloud storage hierarchy.*
2. [**02_modeling_suite.md**](./02_modeling_suite.md)  
   *Core Numerical Engines & Coupling Mechanics: WRF atmospheric physics, CROCO 3D hydrostatic primitive equations ($s$-vertical coordinates), SWAN 3D spectral wave dynamics, and OASIS3-MCT/COAWST two-way and three-way flux exchange mechanics.*
3. [**03_thermodynamics_and_fluxes.md**](./03_thermodynamics_and_fluxes.md)  
   *Physical Formulations & Bulk Parameterization: Thermodynamic surface heat flux equations ($\text{shflux}$ decomposition), resolution of unit conversion errors and uncoupled loops in `bulk_flux.F`, and nocturnal boundary cooling physics.*
4. [**04_empirical_validation.md**](./04_empirical_validation.md)  
   *Balearic Basin Benchmark Case Study: Domain specification ($401 \times 501 \times 32$), July 2026 Gate 8c SST empirical metrics, and coastal latent heat flux anomaly diagnostics off Dragonera Island ($39.58^\circ\text{N}, 2.34^\circ\text{E}$).*
5. [**05_cloud_deployment_and_ops.md**](./05_cloud_deployment_and_ops.md)  
   *GCP Batch Execution & Serverless Infrastructure: Containerized MPI architecture (`predsea-croco-staging`), Spot VM cost optimization, automated self-deletion traps, and multi-tile output consolidation.*
6. [**06_conclusion_and_roadmap.md**](./06_conclusion_and_roadmap.md)  
   *Future Outlook & Engineering Roadmap: Diurnal thermal cycle tracking, full operational CROCO-SWAN wave-current coupling, and automated captain-facing decision APIs.*
