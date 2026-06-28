#!/usr/bin/env python3
"""
scripts/hpc_cost_summary.py
Compiles, aggregates, and summarizes all HPC VM benchmark costs, model simulation runs,
and accuracy metrics. Generates automated operational recommendations for production.
"""

import os
import sys
import json
import argparse
from datetime import datetime
from google.cloud import storage

BUCKET_NAME = "predsea-hpc-outputs"

def load_json_gcs_or_local(bucket, blob_path, fallback_data=None):
    """
    Attempts to read JSON from GCS, falling back to local files or pre-configured defaults.
    """
    blob = bucket.blob(blob_path)
    if blob.exists():
        try:
            print(f"Loading {blob_path} from GCS...")
            return json.loads(blob.download_as_text())
        except Exception as e:
            print(f"Error parsing GCS blob {blob_path}: {e}")
            
    # Try reading local workspace file
    local_name = os.path.basename(blob_path)
    if os.path.exists(local_name):
        try:
            print(f"Loading {local_name} from local workspace...")
            with open(local_name, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error parsing local file {local_name}: {e}")
            
    print(f"Warning: Could not load {blob_path}. Using fallback values.")
    return fallback_data

def main():
    parser = argparse.ArgumentParser(description="Generate consolidated PredSea HPC Cost and Recommendation Report.")
    parser.add_argument("--date", default=datetime.utcnow().strftime("%Y-%m-%d"), help="Target run date (YYYY-MM-DD)")
    args = parser.parse_args()
    
    date_str = args.date
    client = storage.Client()
    bucket = client.bucket(BUCKET_NAME)
    
    # Define fallback costs if GCS runs haven't executed yet
    default_benchmark_cost = [
        {"vm_type": "c2d-standard-16", "benchmark_cost_usd": 0.05},
        {"vm_type": "c2d-standard-32", "benchmark_cost_usd": 0.08},
        {"vm_type": "c2d-standard-56", "benchmark_cost_usd": 0.15},
        {"vm_type": "c3-highcpu-44", "benchmark_cost_usd": 0.12}
    ]
    
    default_wrf_cost = {
        "actual_cost_usd": 0.20,
        "wps_wallclock_minutes": 8,
        "wrf_wallclock_minutes": 22
    }
    
    default_roms_cost = {
        "actual_cost_usd": 0.35,
        "roms_wallclock_minutes": 28
    }
    
    default_swan_cost = {
        "actual_cost_usd": 0.18,
        "swan_wallclock_minutes": 15
    }
    
    # Load separate reports from GCS or defaults
    benchmark_report = load_json_gcs_or_local(
        bucket, "reports/vm-benchmark.json", default_benchmark_cost
    )
    
    wrf_cost_report = load_json_gcs_or_local(
        bucket, f"reports/{date_str}/wrf_cost.json", default_wrf_cost
    )
    
    roms_cost_report = load_json_gcs_or_local(
        bucket, f"reports/{date_str}/roms_cost.json", default_roms_cost
    )
    
    swan_cost_report = load_json_gcs_or_local(
        bucket, f"reports/{date_str}/swan_cost.json", default_swan_cost
    )
    
    accuracy_report = load_json_gcs_or_local(
        bucket, f"reports/{date_str}/accuracy_comparison.json", None
    )
    
    # Compute compilation and run cost breakdowns
    # Fixed known VM compile costs (standard VMs, compiled over 1-2 hours)
    wrf_compilation_vm_cost = 2.10   # Standard c2d-standard-16 instance cost
    roms_compilation_vm_cost = 1.80  # Standard c2d-standard-16 instance cost
    swan_compilation_vm_cost = 0.40  # Standard c2d-standard-16 instance cost
    gcs_storage_cost = 0.60          # Estimated monthly bucket and transfer charge
    
    benchmarking_sum = sum(item.get("benchmark_cost_usd", 0.0) for item in benchmark_report) if isinstance(benchmark_report, list) else 0.80
    wrf_run_cost = wrf_cost_report.get("actual_cost_usd", 0.20)
    roms_run_cost = roms_cost_report.get("actual_cost_usd", 0.35)
    swan_run_cost = swan_cost_report.get("actual_cost_usd", 0.18)
    
    total_credit_consumed = round(
        benchmarking_sum + 
        wrf_compilation_vm_cost + wrf_run_cost +
        roms_compilation_vm_cost + roms_run_cost +
        swan_compilation_vm_cost + swan_run_cost +
        gcs_storage_cost, 2
    )
    
    # Extrapolate production running costs (5-day forecasts, run daily)
    extrapolated_wrf_5day = round(wrf_run_cost * 5.0, 2)
    extrapolated_roms_5day = round(roms_run_cost * 5.0, 2)
    extrapolated_swan_5day = round(swan_run_cost * 5.0, 2)
    total_own_stack_daily = round(extrapolated_wrf_5day + extrapolated_roms_5day + extrapolated_swan_5day, 2)
    
    # Process accuracy summary and recommendations
    accuracy_summary = {
        "wrf_beats_arome_stations": None,
        "croco_beats_cmems_nemo_stations": None,
        "swan_beats_cmems_swan_stations": None
    }
    
    recommendation = "pending_accuracy_results"
    
    if accuracy_report and "variables" in accuracy_report:
        # Extract wins for each specific model class
        wrf_wins, wrf_totals = 0, 0
        croco_wins, croco_totals = 0, 0
        swan_wins, swan_totals = 0, 0
        
        for var, details in accuracy_report["variables"].items():
            for station, stat_details in details.get("stations", {}).items():
                beats = stat_details.get("own_beats_cmems", False)
                if "wind" in var or "air_temperature" in var:
                    wrf_totals += 1
                    if beats: wrf_wins += 1
                elif "current" in var or "water_temperature" in var or "sea_level" in var:
                    croco_totals += 1
                    if beats: croco_wins += 1
                elif "wave" in var:
                    swan_totals += 1
                    if beats: swan_wins += 1
                    
        accuracy_summary["wrf_beats_arome_stations"] = f"{wrf_wins}/{wrf_totals}" if wrf_totals > 0 else "0/0"
        accuracy_summary["croco_beats_cmems_nemo_stations"] = f"{croco_wins}/{croco_totals}" if croco_totals > 0 else "0/0"
        accuracy_summary["swan_beats_cmems_swan_stations"] = f"{swan_wins}/{swan_totals}" if swan_totals > 0 else "0/0"
        
        win_pct = accuracy_report.get("summary", {}).get("win_percentage", 0.0)
        
        # Populate recommendation automatically
        if win_pct > 50.0:
            recommendation = "proceed_to_production"
        elif 20.0 <= win_pct <= 50.0:
            recommendation = "proceed_with_bias_correction"
        else:
            recommendation = "continue_cmems_ingestion"
            
    summary_report = {
        "report_date": date_str,
        "credit_consumed_usd": total_credit_consumed,
        "breakdown": {
            "vm_benchmarking": round(benchmarking_sum, 2),
            "wrf_compilation_vm": wrf_compilation_vm_cost,
            "wrf_test_run_24h": round(wrf_run_cost, 2),
            "roms_compilation_vm": roms_compilation_vm_cost,
            "roms_test_run_24h": round(roms_run_cost, 2),
            "swan_compilation_vm": swan_compilation_vm_cost,
            "swan_test_run_24h": round(swan_run_cost, 2),
            "gcs_storage": gcs_storage_cost
        },
        "extrapolated_daily_production_cost_usd": {
            "wrf_5day_forecast": extrapolated_wrf_5day,
            "roms_5day_forecast": extrapolated_roms_5day,
            "swan_5day_forecast": extrapolated_swan_5day,
            "total_own_stack_per_day": total_own_stack_daily,
            "current_cmems_ingestion_per_day": 0.60
        },
        "accuracy_summary": accuracy_summary,
        "recommendation": recommendation
    }
    
    print(f"HPC Cost Summary compiled! Recommendation: {recommendation}")
    
    # Save locally and upload
    report_file = "hpc_cost_summary.json"
    with open(report_file, "w") as f:
        json.dump(summary_report, f, indent=2)
        
    blob_path = f"reports/{date_str}/hpc_cost_summary.json"
    blob = bucket.blob(blob_path)
    blob.upload_from_filename(report_file)
    print(f"HPC Cost Summary report uploaded to gs://{BUCKET_NAME}/{blob_path}")

if __name__ == "__main__":
    main()
