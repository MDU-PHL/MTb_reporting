#!/usr/bin/env python3
"""
Merge per-lineage cleptr cluster databases into a unified cross-lineage database.

For each specified TB lineage, this script:
  1. Backs up active databases into a dedicated timestamped backup folder:
     <cleptr_db>/Lineage_<N>/backups/<run_ts>/
  2. Generates lineage-prefixed cluster and sample databases with deterministic sorting:
     - possible_clusters_prefix.json
     - possible_samples_prefix.json
     Prefixes cluster labels with 'L{lineage}-' (e.g. 'L1-12', 'L2-UC').
  3. Canonically sorts all clusters (natural ordering) and sample lists.
  4. Compares against the previous merged database to produce a change summary:
     - New clusters added
     - Existing clusters that gained new isolates
     - Any removed clusters or isolates (anomalies)
  5. Saves the canonical merged database:
     <cleptr_db>/merge_db.json
"""

import argparse
import datetime
import json
import logging
import os
import pathlib
import shutil
import sys
from typing import Dict, List, Optional, Tuple

# Constants
DEFAULT_CLEPTR_DB_PATH = "/home/mdu/analysis/surveillance/MTB_cleptr/cleptr_db"
DEFAULT_LINEAGES = "1,2,3,4"
DEFAULT_OUTPUT_NAME = "merge_db.json"
LOG_FORMAT = "[%(asctime)s] <%(levelname)s> %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Prefix and merge per-lineage cleptr cluster databases into a unified canonical database.",
        epilog="""Usage examples:
  # Standard run for default lineages (1, 2, 3, 4):
  python3 merge_cluster_db.py

  # Include lineage 5 and specify custom database path:
  python3 merge_cluster_db.py -l 1,2,3,4,5 -c /path/to/cleptr_db

  # Dry-run with verbose DEBUG logging:
  python3 merge_cluster_db.py -l 1,2,3,4,5 -n -v
""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
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
        "-o", "--output-name",
        default=DEFAULT_OUTPUT_NAME,
        help=f"Filename for the merged cluster JSON in cleptr_db (default: {DEFAULT_OUTPUT_NAME})",
    )
    parser.add_argument(
        "-n", "--dry-run",
        action="store_true",
        default=False,
        help="Simulate execution without writing files or modifying databases",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        default=False,
        help="Enable verbose DEBUG logging",
    )
    return parser.parse_args()


def load_json(file_path: str) -> dict:
    """
    Safely load a JSON file with validation.

    Raises
    ------
    FileNotFoundError
        If the file does not exist.
    ValueError
        If the file contains invalid JSON.
    """
    if not pathlib.Path(file_path).is_file():
        raise FileNotFoundError(f"Database file not found: {file_path}")
    with open(file_path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Corrupt JSON at '{file_path}': {exc}") from exc


def save_json(data: dict, file_path: str, dry_run: bool = False) -> None:
    """Save dictionary to formatted JSON."""
    if dry_run:
        logging.info("[DRY-RUN] Would save JSON to %s (%d keys)", file_path, len(data))
        return
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
    logging.debug("Saved JSON to %s", file_path)


def backup_file(source_path: str, backup_dir: str, dry_run: bool = False) -> Optional[str]:
    """Copy a file into a backup directory if it exists."""
    if not pathlib.Path(source_path).is_file():
        return None
    dest_path = os.path.join(backup_dir, os.path.basename(source_path))
    if dry_run:
        logging.info("[DRY-RUN] Would backup %s → %s", source_path, dest_path)
        return dest_path
    os.makedirs(backup_dir, exist_ok=True)
    shutil.copy2(source_path, dest_path)
    logging.debug("Backed up %s → %s", source_path, dest_path)
    return dest_path


def backup_lineage_databases(lineage_dir: str, backup_dir: str, dry_run: bool = False) -> None:
    """Back up all standard cleptr database files in a lineage directory."""
    target_files = [
        "possible_clusters.json",
        "possible_samples.json",
        "possible_clusters_prefix.json",
        "possible_samples_prefix.json",
    ]
    for filename in target_files:
        full_path = os.path.join(lineage_dir, filename)
        backup_file(full_path, backup_dir, dry_run=dry_run)


def cluster_sort_key(cluster_key: str) -> Tuple[int, int, int, str]:
    """
    Deterministic natural sort key for cluster labels (e.g. 'L1-1', 'L1-10', 'L1-UC').

    Sorting priority:
      1. Lineage number (int, e.g. L1 -> 1, L2 -> 2)
      2. Group type: 0 for numeric clusters, 1 for 'UC' (unclustered), 2 for other tags
      3. Cluster number (int, e.g. 1, 2, 10)
      4. Fallback string
    """
    parts = cluster_key.split("-", 1)
    lin_str = parts[0]

    lin_num = 999
    if lin_str.startswith("L") and lin_str[1:].isdigit():
        lin_num = int(lin_str[1:])
    elif lin_str.isdigit():
        lin_num = int(lin_str)

    if len(parts) > 1:
        suffix = parts[1]
        if suffix.isdigit():
            return (lin_num, 0, int(suffix), suffix)
        if suffix == "UC":
            return (lin_num, 1, 0, suffix)
        return (lin_num, 2, 0, suffix)

    return (lin_num, 3, 0, cluster_key)


def generate_lineage_prefixes(
    lineage: str,
    lineage_dir: str,
    dry_run: bool = False,
) -> Tuple[Dict[str, List[str]], dict]:
    """
    Read raw lineage databases and generate prefixed equivalents with 'L{lineage}-'.
    Applies deterministic sorting to cluster keys and isolate lists.

    Parameters
    ----------
    lineage : str
        Lineage number (e.g. '1', '2').
    lineage_dir : str
        Directory containing the lineage databases.
    dry_run : bool
        If True, simulate without writing files.

    Returns
    -------
    Tuple[Dict[str, List[str]], dict]
        Prefixed cluster dictionary and prefixed sample dictionary.
    """
    cluster_db_path = os.path.join(lineage_dir, "possible_clusters.json")
    sample_db_path = os.path.join(lineage_dir, "possible_samples.json")

    cluster_db = load_json(cluster_db_path)
    sample_db = load_json(sample_db_path)

    prefix = f"L{lineage}-"

    # Sort cluster keys naturally and sort sample lists inside each cluster
    def raw_key_sort(k: str) -> Tuple[int, int, str]:
        if k.isdigit():
            return (0, int(k), k)
        if k == "UC":
            return (1, 0, k)
        return (2, 0, k)

    new_cluster_db: Dict[str, List[str]] = {}
    for cluster_name in sorted(cluster_db.keys(), key=raw_key_sort):
        prefixed_name = f"{prefix}{cluster_name}"
        new_cluster_db[prefixed_name] = sorted(cluster_db[cluster_name])

    # Prefix sample database cluster histories
    new_sample_db: dict = {}
    for sample_id in sorted(sample_db.keys()):
        sample_entry = dict(sample_db[sample_id])
        c_dict = sample_entry.get("clusters", {})
        prefixed_clusters = {date: f"{prefix}{c_val}" for date, c_val in c_dict.items()}
        sample_entry["clusters"] = prefixed_clusters
        new_sample_db[sample_id] = sample_entry

    out_cluster_path = os.path.join(lineage_dir, "possible_clusters_prefix.json")
    out_sample_path = os.path.join(lineage_dir, "possible_samples_prefix.json")

    save_json(new_cluster_db, out_cluster_path, dry_run=dry_run)
    save_json(new_sample_db, out_sample_path, dry_run=dry_run)

    logging.info(
        "Lineage %s: generated prefixed databases (%d clusters, %d samples)",
        lineage, len(new_cluster_db), len(new_sample_db),
    )
    return new_cluster_db, new_sample_db


def summarise_db_changes(
    old_db: Dict[str, List[str]],
    new_db: Dict[str, List[str]],
) -> str:
    """
    Compare previous and new cluster databases and generate a human-readable diff summary.

    Parameters
    ----------
    old_db : dict
        Previous merged cluster database.
    new_db : dict
        New merged cluster database.

    Returns
    -------
    str
        Formatted change summary text report.
    """
    old_clusters = set(old_db.keys())
    new_clusters = set(new_db.keys())

    added_clusters = sorted(new_clusters - old_clusters, key=cluster_sort_key)
    removed_clusters = sorted(old_clusters - new_clusters, key=cluster_sort_key)
    common_clusters = sorted(old_clusters & new_clusters, key=cluster_sort_key)

    old_total_isolates = sum(len(v) for v in old_db.values())
    new_total_isolates = sum(len(v) for v in new_db.values())

    lines = [
        "=" * 65,
        "SURVEILLANCE CLUSTER DATABASE CHANGE SUMMARY",
        "=" * 65,
        f"Previous Database : {len(old_clusters)} clusters, {old_total_isolates} isolate assignments",
        f"New Database      : {len(new_clusters)} clusters, {new_total_isolates} isolate assignments",
    ]
    net_iso = new_total_isolates - old_total_isolates
    lines.append(f"Net Growth        : {len(added_clusters)} new cluster(s), {net_iso:+d} isolate assignment(s)")
    lines.append("-" * 65)

    if added_clusters:
        lines.append(f"NEW CLUSTERS ADDED ({len(added_clusters)}):")
        for c in added_clusters:
            samples = new_db[c]
            preview = ", ".join(samples[:5]) + ("..." if len(samples) > 5 else "")
            lines.append(f"  + {c}: {len(samples)} isolate(s) -> [{preview}]")
        lines.append("")

    if removed_clusters:
        lines.append(f"CLUSTERS REMOVED ({len(removed_clusters)}) [WARNING: verify if expected]:")
        for c in removed_clusters:
            samples = old_db[c]
            lines.append(f"  - {c}: previously had {len(samples)} isolate(s)")
        lines.append("")

    # Check for membership growth / shrink in existing clusters
    growing_clusters = []
    shrinking_clusters = []
    for c in common_clusters:
        old_set = set(old_db[c])
        new_set = set(new_db[c])
        added_samples = sorted(new_set - old_set)
        removed_samples = sorted(old_set - new_set)
        if added_samples:
            growing_clusters.append((c, added_samples, len(old_set), len(new_set)))
        if removed_samples:
            shrinking_clusters.append((c, removed_samples, len(old_set), len(new_set)))

    if growing_clusters:
        lines.append(f"EXISTING CLUSTERS WITH NEW ISOLATES ({len(growing_clusters)}):")
        for c, new_samples, old_len, new_len in growing_clusters:
            preview = ", ".join(new_samples[:5]) + ("..." if len(new_samples) > 5 else "")
            lines.append(f"  * {c}: +{len(new_samples)} new isolate(s) (size: {old_len} -> {new_len})")
            lines.append(f"      added: [{preview}]")
        lines.append("")

    if shrinking_clusters:
        lines.append(f"EXISTING CLUSTERS WITH REMOVED ISOLATES ({len(shrinking_clusters)}) [WARNING]:")
        for c, lost_samples, old_len, new_len in shrinking_clusters:
            preview = ", ".join(lost_samples[:5]) + ("..." if len(lost_samples) > 5 else "")
            lines.append(f"  ! {c}: -{len(lost_samples)} isolate(s) (size: {old_len} -> {new_len})")
            lines.append(f"      removed: [{preview}]")
        lines.append("")

    if not added_clusters and not removed_clusters and not growing_clusters and not shrinking_clusters:
        lines.append("No changes detected — cluster database is identical to previous.")

    lines.append("=" * 65)
    return "\n".join(lines)


def main() -> None:
    """Main execution function."""
    args = parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level, format=LOG_FORMAT, datefmt=DATE_FORMAT)

    lineage_list = [l.strip() for l in args.lineages.split(",") if l.strip()]
    run_ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    try:
        logging.info("Starting MTB cluster database merge")
        logging.info("Lineages         : %s", lineage_list)
        logging.info("cleptr DB path   : %s", args.cleptr_db_path)
        logging.info("Output file      : %s", args.output_name)
        logging.info("Run timestamp    : %s", run_ts)
        logging.info("Dry-run mode     : %s", args.dry_run)

        merged_cluster_db: Dict[str, List[str]] = {}
        failed_lineages = []

        # 1. Process each lineage: backup and generate prefixed databases
        for lineage in lineage_list:
            lineage_dir = os.path.join(args.cleptr_db_path, f"Lineage_{lineage}")
            if not pathlib.Path(lineage_dir).is_dir():
                logging.error("Directory not found: %s — skipping lineage %s", lineage_dir, lineage)
                failed_lineages.append(lineage)
                continue
            
            # append _MCD to backup_dir to avoid overwriting backups from other scripts
            # backup_dir = os.path.join(lineage_dir, "backups", run_ts, "MCD")
            backup_dir = os.path.join(lineage_dir, "backups", run_ts + "_MCD")

            # backup_dir = os.path.join(lineage_dir, "backups", run_ts)

            try:
                # Backup pre-existing files
                backup_lineage_databases(lineage_dir, backup_dir, dry_run=args.dry_run)

                # Generate prefixed files with sorted keys and samples
                prefixed_clusters, _ = generate_lineage_prefixes(
                    lineage=lineage,
                    lineage_dir=lineage_dir,
                    dry_run=args.dry_run,
                )

                # Collect into merged database
                for cluster_key, samples in prefixed_clusters.items():
                    if cluster_key in merged_cluster_db:
                        logging.warning(
                            "Unexpected duplicate cluster key '%s' across lineages; overwriting with Lineage %s data.",
                            cluster_key, lineage,
                        )
                    merged_cluster_db[cluster_key] = samples

            except Exception as exc:
                logging.error("Failed processing Lineage %s: %s", lineage, exc, exc_info=args.verbose)
                failed_lineages.append(lineage)

        if failed_lineages:
            logging.error("Database merge completed with errors in lineage(s): %s", ", ".join(failed_lineages))
            sys.exit(1)

        # 2. Canonical natural sorting of all clusters and their sample lists
        sorted_merged_db: Dict[str, List[str]] = {}
        for cluster_key in sorted(merged_cluster_db.keys(), key=cluster_sort_key):
            sorted_merged_db[cluster_key] = sorted(merged_cluster_db[cluster_key])

        # 3. Compare against previous database if it exists
        output_db_path = os.path.join(args.cleptr_db_path, args.output_name)
        root_backup_dir = os.path.join(args.cleptr_db_path, "backups", run_ts + "_MCD")
        if pathlib.Path(output_db_path).is_file():
            try:
                previous_db = load_json(output_db_path)
                change_summary = summarise_db_changes(previous_db, sorted_merged_db)

                # Print summary report to log
                for line in change_summary.splitlines():
                    logging.info(line)

                # Save change report text file alongside the backup
                if not args.dry_run:
                    os.makedirs(root_backup_dir, exist_ok=True)
                    summary_path = os.path.join(root_backup_dir, "merge_db_changes.txt")
                    with open(summary_path, "w", encoding="utf-8") as s_out:
                        s_out.write(change_summary + "\n")
                    logging.info("Saved change summary report to %s", summary_path)
            except Exception as exc:
                logging.warning("Could not compute database diff summary: %s", exc)

        # 4. Backup existing merged database before overwriting
        backup_file(output_db_path, root_backup_dir, dry_run=args.dry_run)

        # 5. Save canonical merged database
        save_json(sorted_merged_db, output_db_path, dry_run=args.dry_run)
        logging.info(
            "Successfully merged %d total clusters across %d lineages into %s",
            len(sorted_merged_db), len(lineage_list), output_db_path,
        )

        logging.info("All cluster names updated. Next step: run combine.py to generate report files.")
        logging.info("Done.")

    except Exception as exc:
        logging.error("Fatal error during merge execution: %s", exc, exc_info=args.verbose)
        sys.exit(1)


if __name__ == "__main__":
    main()

