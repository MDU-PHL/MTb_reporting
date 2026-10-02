#!/usr/bin/env python3
"""
Combine primary (Tx:12) and high-resolution (Tx:5) cleptr cluster assignments
into a unified hierarchical cluster nomenclature table for MTB surveillance reporting.

Outputs per lineage:
  - lineage_{lineage}.{date}.csv (read by MTB_new_report.py)
  - cluster.{date}.json
"""

import argparse
import glob
import json
import logging
import os
import pathlib
import sys
from typing import Dict, List, Optional

import pandas as pd

# Constants
DEFAULT_CLEPTR_DB_PATH = "/home/mdu/analysis/surveillance/MTB_cleptr/cleptr_db"
DEFAULT_LINEAGES = "1,2,3,4"
LOG_FORMAT = "[%(asctime)s] <%(levelname)s> %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Compile hierarchical cleptr cluster IDs (Tx:12 + Tx:5) into report tables.",
        epilog="""Usage examples:
  # Process all default lineages (1-4) for a given date:
  python3 combine.py -d 2026-09-14

  # Process specific lineages including lineage 5:
  python3 combine.py -d 2026-09-14 -l 1,2,3,4,5

  # Dry-run with custom database directory and verbose logging:
  python3 combine.py -d 2026-09-14 -c /custom/path/cleptr_db -n -v
""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-d", "--date",
        dest="mdate",
        required=True,
        help="Date suffix for output files (e.g. 2026-09-14)",
    )
    parser.add_argument(
        "-l", "--lineages",
        default=DEFAULT_LINEAGES,
        help=f"Comma-separated lineage numbers to process (default: {DEFAULT_LINEAGES})",
    )
    parser.add_argument(
        "-c", "--cleptr-db-path",
        default=DEFAULT_CLEPTR_DB_PATH,
        help=f"Path to the cleptr database root (default: {DEFAULT_CLEPTR_DB_PATH})",
    )
    parser.add_argument(
        "-n", "--dry-run",
        action="store_true",
        default=False,
        help="Simulate processing without writing files to disk",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        default=False,
        help="Enable verbose DEBUG logging",
    )
    return parser.parse_args()


def load_json(file_path: str) -> Optional[dict]:
    """Load JSON file safely with error handling."""
    if not pathlib.Path(file_path).is_file():
        logging.warning("File not found: %s", file_path)
        return None
    with open(file_path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as exc:
            logging.error("Corrupt JSON file '%s': %s", file_path, exc)
            return None


def log_new_assignments(lineage: str, mdate: str, lineage_dir: str, new_df: pd.DataFrame) -> None:
    """
    Auto-detect the most recent previous output CSV in lineage_dir and log a
    concise diff of new and changed cluster assignments.

    No previous date argument is required — the most recent CSV is found by
    sorting existing lineage_<lin>.*.csv files and picking the last one that
    does NOT match the current mdate.
    """
    pattern = os.path.join(lineage_dir, f"lineage_{lineage}.*.csv")
    existing = sorted(
        [f for f in glob.glob(pattern) if f"{mdate}" not in os.path.basename(f)]
    )
    if not existing:
        logging.info("Lineage %s: no previous report CSV found — first run, all %d isolates are new.", lineage, len(new_df))
        _log_cluster_summary(lineage, new_df)
        return

    prev_path = existing[-1]
    prev_date = os.path.basename(prev_path).split(".")[1] if "." in os.path.basename(prev_path) else "?"
    logging.info("Lineage %s: comparing against previous report: %s (date: %s)", lineage, os.path.basename(prev_path), prev_date)

    try:
        prev_df = pd.read_csv(prev_path)
    except Exception as exc:
        logging.warning("Lineage %s: could not load previous CSV (%s) — skipping diff.", lineage, exc)
        _log_cluster_summary(lineage, new_df)
        return

    # Key on Seq_ID for comparison
    prev_map = prev_df.set_index("Seq_ID")["Cluster_ID"].to_dict() if "Seq_ID" in prev_df.columns and "Cluster_ID" in prev_df.columns else {}
    new_map = new_df.set_index("Seq_ID")["Cluster_ID"].to_dict()

    newly_added = {sid: cid for sid, cid in new_map.items() if sid not in prev_map and cid != "UC"}
    newly_uc = {sid: cid for sid, cid in new_map.items() if sid not in prev_map and cid == "UC"}
    changed = {sid: (prev_map[sid], new_map[sid]) for sid in new_map if sid in prev_map and prev_map[sid] != new_map[sid]}
    removed = {sid for sid in prev_map if sid not in new_map}

    sep = "-" * 55
    logging.info(sep)
    logging.info("LINEAGE %s — CLUSTER ASSIGNMENT CHANGES", lineage)
    logging.info(sep)
    logging.info("  Total isolates  : %d (previous: %d)", len(new_map), len(prev_map))
    logging.info("  New clustered   : %d", len(newly_added))
    logging.info("  New unclustered : %d", len(newly_uc))
    logging.info("  Reclassified    : %d", len(changed))
    if removed:
        logging.warning("  Removed IDs     : %d  [VERIFY — isolates present in previous run but not this one]", len(removed))

    if newly_added:
        logging.info("  --- Newly clustered isolates ---")
        for sid, cid in sorted(newly_added.items()):
            logging.info("    + %-25s -> %s", sid, cid)

    if newly_uc:
        logging.info("  --- Newly unclustered isolates (UC) ---")
        for sid in sorted(newly_uc):
            logging.info("    + %-25s -> UC", sid)

    if changed:
        logging.info("  --- Reclassified isolates ---")
        for sid, (old_cid, new_cid) in sorted(changed.items()):
            logging.info("    * %-25s  %s -> %s", sid, old_cid, new_cid)

    if removed:
        logging.warning("  --- Removed isolates (missing from new run) ---")
        for sid in sorted(removed):
            logging.warning("    ! %-25s was: %s", sid, prev_map[sid])

    logging.info(sep)


def _log_cluster_summary(lineage: str, df: pd.DataFrame) -> None:
    """Log a per-cluster breakdown of isolate counts."""
    clustered = df[df["Cluster_poss"] != "UC"]
    if clustered.empty:
        return
    counts = clustered.groupby("Cluster_ID")["Seq_ID"].count().sort_index()
    logging.info("  --- Cluster breakdown (Lineage %s) ---", lineage)
    for cid, count in counts.items():
        logging.info("    %-30s : %d isolate(s)", cid, count)


def process_lineage_clusters(
    lineage: str,
    mdate: str,
    lineage_dir: str,
    dry_run: bool = False,
) -> pd.DataFrame:
    """
    Compile hierarchical cluster IDs for a single lineage.

    Parameters
    ----------
    lineage : str
        Lineage identifier (e.g. '1', '2').
    mdate : str
        Report date string.
    lineage_dir : str
        Path to the Lineage directory containing possible_samples.json.
    dry_run : bool
        If True, skip writing output files.

    Returns
    -------
    pd.DataFrame
        Compiled cluster summary table.
    """
    samples_json_path = os.path.join(lineage_dir, "possible_samples.json")
    logging.info("Processing Lineage %s from %s", lineage, lineage_dir)

    possible_samples = load_json(samples_json_path)
    if possible_samples is None:
        raise FileNotFoundError(f"Could not load required database: {samples_json_path}")

    records = []
    subcluster_cache: Dict[str, Optional[dict]] = {}

    for sample_id, sample_data in possible_samples.items():
        curr_key = sample_data.get("current")
        clusters_dict = sample_data.get("clusters", {})
        poss_cluster = clusters_dict.get(curr_key, "UC") if curr_key else "UC"

        if poss_cluster != "UC":
            # Cache subcluster JSON loads to avoid re-reading the same file repeatedly
            if poss_cluster not in subcluster_cache:
                sub_file = os.path.join(lineage_dir, f"clst_{poss_cluster}_samples.json")
                subcluster_cache[poss_cluster] = load_json(sub_file)

            scl_data = subcluster_cache[poss_cluster]
            if scl_data and sample_id in scl_data:
                sub_curr = scl_data[sample_id].get("current")
                sub_clusters = scl_data[sample_id].get("clusters", {})
                subcluster = sub_clusters.get(sub_curr, "UC") if sub_curr else "UC"
            else:
                subcluster = "UC"

            cluster_id = f"L{lineage}-{poss_cluster}-{subcluster}"
        else:
            subcluster = "UC"
            cluster_id = "UC"

        records.append({
            "Seq_ID": sample_id,
            "Cluster_poss": poss_cluster,
            "Cluster_highly": subcluster,
            "Cluster_ID": cluster_id,
        })

    df = pd.DataFrame(records)
    n_clustered = len(df[df["Cluster_poss"] != "UC"])
    logging.info(
        "Lineage %s: %d total isolates (%d clustered, %d unclustered)",
        lineage, len(df), n_clustered, len(df) - n_clustered,
    )

    # Log new assignments vs previous run — auto-detected, no date arg needed
    log_new_assignments(lineage=lineage, mdate=mdate, lineage_dir=lineage_dir, new_df=df)

    # Output file destinations
    out_csv = os.path.join(lineage_dir, f"lineage_{lineage}.{mdate}.csv")
    out_json = os.path.join(lineage_dir, f"cluster.{mdate}.json")

    if not dry_run:
        with open(out_json, "w", encoding="utf-8") as j_out:
            json.dump(records, j_out, indent=4)
        df.to_csv(out_csv, index=False)
        logging.info("Saved outputs: %s and %s", out_csv, out_json)
    else:
        logging.info("[DRY-RUN] Would save %s and %s", out_csv, out_json)

    return df


def main() -> None:
    """Main execution function."""
    args = parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level, format=LOG_FORMAT, datefmt=DATE_FORMAT)

    lineage_list = [l.strip() for l in args.lineages.split(",") if l.strip()]

    try:
        logging.info("Starting cleptr cluster combination")
        logging.info("Date suffix    : %s", args.mdate)
        logging.info("Lineages       : %s", lineage_list)
        logging.info("cleptr DB path : %s", args.cleptr_db_path)
        logging.info("Dry-run mode   : %s", args.dry_run)

        failed_lineages = []

        for lineage in lineage_list:
            lineage_dir = os.path.join(args.cleptr_db_path, f"Lineage_{lineage}")
            try:
                process_lineage_clusters(
                    lineage=lineage,
                    mdate=args.mdate,
                    lineage_dir=lineage_dir,
                    dry_run=args.dry_run,
                )
            except Exception as err:
                logging.error("Failed processing Lineage %s: %s", lineage, err, exc_info=args.verbose)
                failed_lineages.append(lineage)

        if failed_lineages:
            logging.error("Combination finished with failures in lineage(s): %s", ", ".join(failed_lineages))
            sys.exit(1)

        logging.info("All lineages combined successfully. Done.")

    except Exception as err:
        logging.error("Fatal error during execution: %s", err, exc_info=args.verbose)
        sys.exit(1)


if __name__ == "__main__":
    main()
