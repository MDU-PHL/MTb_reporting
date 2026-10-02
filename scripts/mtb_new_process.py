#!/usr/bin/env python3
"""
MTB cleptr reporting pipeline orchestrator.

For each specified TB lineage, this script:
  1. Copies the fresh SNP cluster file into the cleptr database directory.
  2. Labels singleton clusters as 'UC' (unclustered), logic previously in make_uc.py.
  3. Runs cleptr to update the lineage-level (Tx:12) nomenclature database.
  4. Generates the cleptr cluster report.
  5. Updates per-cluster high-resolution (Tx:5) databases, logic previously in make_high.py.

make_uc.py and make_high.py are no longer required as separate files in each
Lineage directory. Their logic lives here as plain Python functions.
"""

import argparse
import datetime
import json
import logging
import os
import pathlib
import shutil
import subprocess
import sys
from typing import List

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Constants — override via CLI if your paths differ
# ---------------------------------------------------------------------------
DEFAULT_ANALYSIS_PATH = "/home/mdu/analysis/surveillance/tb_dev"
DEFAULT_CLEPTR_DB_PATH = "/home/mdu/analysis/surveillance/MTB_cleptr/cleptr_db"
DEFAULT_LINEAGES = "1,2,3,4"
CLUSTER_COL_LINEAGE = "Tx:12"
CLUSTER_COL_HIGH = "Tx:5"
ID_COL = "Seq_ID"

LOG_FORMAT = "[%(asctime)s] <%(levelname)s> %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="MTB SNP-cluster cleptr processing.",
        epilog="""Usage examples:
  # Standard run for lineages 1-4 on a specific date:
  python3 mtb_new_process.py -d 2026-09-14

  # Include lineage 5 and override the analysis path:
  python3 mtb_new_process.py -d 2026-09-14 -l 1,2,3,4,5 -a /path/to/tb_dev

  # Dry-run to see what commands would be executed:
  python3 mtb_new_process.py -d 2026-09-14 --dry-run

  # Verbose output:
  python3 mtb_new_process.py -d 2026-09-14 -v
""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-d", "--date",
        dest="mdate",
        required=True,
        help="Date suffix for cluster files, e.g. 2026-09-14",
    )
    parser.add_argument(
        "-l", "--lineages",
        default=DEFAULT_LINEAGES,
        help=f"Comma-separated lineage numbers to process (default: {DEFAULT_LINEAGES})",
    )
    parser.add_argument(
        "-a", "--analysis-path",
        default=DEFAULT_ANALYSIS_PATH,
        help=f"Path to the TB analysis directory containing Lineage_N subdirs (default: {DEFAULT_ANALYSIS_PATH})",
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
        help="Print commands that would be run but do not execute them",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        default=False,
        help="Enable DEBUG-level logging",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Shell command runner — replaces the old bash_command() that silently
# discarded non-zero exit codes
# ---------------------------------------------------------------------------

def run_cmd(cmd: str, step: str, cwd: str = None, dry_run: bool = False) -> None:
    """
    Run a shell command, log stdout/stderr, and raise on non-zero exit.

    Parameters
    ----------
    cmd : str
        Shell command to execute.
    step : str
        Human-readable label for this step (used in log messages).
    cwd : str, optional
        Working directory to execute the command in.
    dry_run : bool
        If True, log the command but do not execute it.

    Raises
    ------
    RuntimeError
        If the command exits with a non-zero return code.
    """
    cwd_str = f" (cwd: {cwd})" if cwd else ""
    logging.info("[%s]%s %s", step, cwd_str, cmd)
    if dry_run:
        logging.info("[DRY-RUN] skipping execution")
        return

    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd)

    if result.stdout.strip():
        logging.debug("[STDOUT] %s", result.stdout.strip())
    if result.stderr.strip():
        # cleptr writes INFO messages to stderr, so log at DEBUG unless failure
        level = logging.WARNING if result.returncode != 0 else logging.DEBUG
        logging.log(level, "[STDERR] %s", result.stderr.strip())

    if result.returncode != 0:
        raise RuntimeError(
            f"Step '{step}' failed (exit {result.returncode}).\nCommand: {cmd}"
        )


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------

def validate_json(path: str) -> dict:
    """
    Load and validate a JSON file.

    Raises
    ------
    ValueError
        If the file is missing or contains invalid JSON.
    """
    if not pathlib.Path(path).is_file():
        raise FileNotFoundError(f"Required JSON not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Corrupt JSON at '{path}': {exc}\n"
                "This is likely caused by a previous interrupted cleptr run. "
                "Restore from the .bak backup in the same directory."
            ) from exc


def backup_json(path: str, backup_dir: str) -> None:
    """Copy a JSON database file into the timestamped backup directory before mutation."""
    if not pathlib.Path(path).is_file():
        return
    os.makedirs(backup_dir, exist_ok=True)
    dest_path = os.path.join(backup_dir, os.path.basename(path))
    shutil.copy2(path, dest_path)
    logging.debug("Backed up %s → %s", path, dest_path)


# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------

def pre_flight_check(lineage: str, mdate: str, analysis_path: str, cleptr_db_path: str) -> None:
    """
    Assert all required inputs exist before starting a lineage run.

    Raises
    ------
    FileNotFoundError
        If any required file or directory is missing.
    """
    source_cluster_file = os.path.join(
        analysis_path, f"Lineage_{lineage}", f"snp_clusters.txt.{mdate}"
    )
    lineage_db_dir = os.path.join(cleptr_db_path, f"Lineage_{lineage}")
    possible_samples = os.path.join(lineage_db_dir, "possible_samples.json")
    possible_clusters = os.path.join(lineage_db_dir, "possible_clusters.json")

    for path in [source_cluster_file, lineage_db_dir, possible_samples, possible_clusters]:
        if not pathlib.Path(path).exists():
            raise FileNotFoundError(
                f"Pre-flight check failed for Lineage {lineage}: path not found: {path}"
            )
    logging.debug("Pre-flight check passed for Lineage %s", lineage)


# ---------------------------------------------------------------------------
# Inlined make_uc logic — was make_uc.py
# ---------------------------------------------------------------------------

def label_singletons_as_uc(
    input_path: str,
    output_path: str,
    cluster_cols: List[str],
    id_col: str = ID_COL,
) -> None:
    """
    Read a SNP cluster file and relabel singleton clusters as 'UC' (unclustered).

    A singleton is a cluster label that appears for exactly one isolate.
    After relabelling, write the result to output_path.

    Parameters
    ----------
    input_path : str
        Tab-delimited SNP cluster file with columns including id_col and each
        column in cluster_cols.
    output_path : str
        Destination path for the UC-labelled output file.
    cluster_cols : list of str
        Column names to check for singletons (e.g. ['Tx:12', 'Tx:5']).
    id_col : str
        Column name for the isolate identifier.
    """
    logging.info("Labelling singletons as UC: %s → %s", input_path, output_path)
    df = pd.read_csv(input_path, sep="\t")

    # Validate required columns
    missing = [c for c in [id_col] + cluster_cols if c not in df.columns]
    if missing:
        raise ValueError(
            f"Input file '{input_path}' is missing expected columns: {missing}. "
            f"Found: {list(df.columns)}"
        )
    if df[id_col].duplicated().any():
        dupes = df[id_col][df[id_col].duplicated()].tolist()
        raise ValueError(f"Duplicate {id_col} values in '{input_path}': {dupes}")

    for col in cluster_cols:
        counts = df.groupby(col)[id_col].transform("count")
        n_singletons = (counts == 1).sum()
        df[col] = np.where(counts == 1, "UC", df[col])
        logging.info("  %-6s: %d singleton(s) relabelled as UC", col, n_singletons)

    df.to_csv(output_path, sep="\t", index=False)
    logging.info("UC-labelled file written: %s (%d rows)", output_path, len(df))


# ---------------------------------------------------------------------------
# Inlined make_high logic — was make_high.py / make_high_lin4.py
# ---------------------------------------------------------------------------

def run_high_res_clusters(
    uc_cluster_file: str,
    possible_clusters_json: str,
    high_col: str,
    id_col: str,
    lineage_db_dir: str,
    backup_dir: str = None,
    dry_run: bool = False,
) -> None:
    """
    For each non-UC cluster in possible_clusters.json, slice isolates from the
    UC-labelled cluster file and run `cleptr run` or `cleptr init` to maintain
    high-resolution (Tx:5) nomenclature.

    Fixes from make_high.py:
    - f-string bug fixed (was printing literal 'clst_{c}')
    - Empty-DataFrame guard added (was make_high_lin4.py improvement)
    - cleptr return code is now checked via run_cmd()
    - JSON integrity validated before reading

    Parameters
    ----------
    uc_cluster_file : str
        Path to the UC-labelled SNP cluster file.
    possible_clusters_json : str
        Path to the lineage-level possible_clusters.json (cleptr state).
    high_col : str
        Column name for the high-resolution threshold (e.g. 'Tx:5').
    id_col : str
        Column name for the isolate identifier.
    lineage_db_dir : str
        The lineage cleptr database directory (all clst_* files live here).
    backup_dir : str
        The timestamped backup directory for this run.
    dry_run : bool
        If True, log commands but do not execute.
    """
    logging.info("Running high-resolution cluster updates (column: %s)", high_col)

    df = pd.read_csv(uc_cluster_file, sep="\t")
    cluster_map = validate_json(possible_clusters_json)

    n_clusters = len([c for c in cluster_map if c != "UC"])
    logging.info("Found %d non-UC clusters to process", n_clusters)

    if backup_dir is None:
        backup_dir = os.path.join(lineage_db_dir, "backups")

    for c, isolates in cluster_map.items():
        if c == "UC":
            continue

        tab = df[df[id_col].isin(isolates)]

        if tab.empty:
            logging.warning(
                "Cluster %s: no rows found in '%s' for %d listed isolates — skipping.",
                c, uc_cluster_file, len(isolates),
            )
            continue

        tmp_file = os.path.join(lineage_db_dir, f"tmp_{c}.txt")
        tab.to_csv(tmp_file, sep="\t", index=False)
        logging.debug("Wrote %d rows to %s", len(tab), tmp_file)

        samples_json = os.path.join(lineage_db_dir, f"clst_{c}_samples.json")
        clusters_json = os.path.join(lineage_db_dir, f"clst_{c}_clusters.json")

        if pathlib.Path(samples_json).exists():
            # Validate before mutating
            validate_json(clusters_json)
            backup_json(samples_json, backup_dir=backup_dir)
            backup_json(clusters_json, backup_dir=backup_dir)
            cmd = (
                f"cleptr run "
                f"-s clst_{c}_samples.json "
                f"-c clst_{c}_clusters.json "
                f"--id_col {id_col} "
                f"--cluster_col '{high_col}' "
                f"-i tmp_{c}.txt"
            )
            run_cmd(cmd, step=f"cleptr-run clst_{c}", cwd=lineage_db_dir, dry_run=dry_run)
        else:
            cmd = (
                f"cleptr init "
                f"--prefix clst_{c} "
                f"-i tmp_{c}.txt "
                f"--id_col {id_col} "
                f"--cluster_col '{high_col}'"
            )
            logging.info("New cluster %s — initialising cleptr database", c)
            run_cmd(cmd, step=f"cleptr-init clst_{c}", cwd=lineage_db_dir, dry_run=dry_run)


# ---------------------------------------------------------------------------
# Per-lineage processing — one lineage at a time, fail-fast
# ---------------------------------------------------------------------------

def process_lineage(
    lineage: str,
    mdate: str,
    analysis_path: str,
    cleptr_db_path: str,
    run_ts: str,
    dry_run: bool,
) -> None:
    """
    Run all five pipeline steps for a single lineage.

    Raises
    ------
    RuntimeError / FileNotFoundError / ValueError
        On any step failure — propagated to caller so the caller can decide
        whether to skip remaining lineages or abort entirely.
    """
    lineage_dir = os.path.join(cleptr_db_path, f"Lineage_{lineage}")
    backup_dir = os.path.join(lineage_dir, "backups", run_ts + "_MNP")
    source = os.path.join(analysis_path, f"Lineage_{lineage}", f"snp_clusters.txt.{mdate}")
    dest_cluster = os.path.join(lineage_dir, f"snp_clusters.txt.{mdate}")
    dest_uc = os.path.join(lineage_dir, f"snp_clusters_uc.txt.{mdate}")
    possible_samples = os.path.join(lineage_dir, "possible_samples.json")
    possible_clusters = os.path.join(lineage_dir, "possible_clusters.json")
    cleptr_log = os.path.join(lineage_dir, "cleptr.log")

    logging.info("=" * 60)
    logging.info("Processing Lineage %s  (date: %s, backup: %s)", lineage, mdate, backup_dir)
    logging.info("=" * 60)

    # Archive previous cleptr.log to the timestamped backup directory if it exists
    if not dry_run and pathlib.Path(cleptr_log).is_file():
        os.makedirs(backup_dir, exist_ok=True)
        shutil.move(cleptr_log, os.path.join(backup_dir, "cleptr.log"))
        logging.info("Archived existing cleptr.log → %s", os.path.join(backup_dir, "cleptr.log"))

    # STEP 1 — Copy fresh cluster file
    logging.info("[STEP 1] Copying cluster file to cleptr db")
    if not dry_run:
        shutil.copy2(source, dest_cluster)
        logging.info("Copied %s → %s", source, dest_cluster)
    else:
        logging.info("[DRY-RUN] Would copy %s → %s", source, dest_cluster)

    # STEP 2 — Label singletons as UC (was make_uc.py)
    logging.info("[STEP 2] Labelling singletons as UC")
    if not dry_run:
        label_singletons_as_uc(
            input_path=dest_cluster,
            output_path=dest_uc,
            cluster_cols=[CLUSTER_COL_LINEAGE, CLUSTER_COL_HIGH],
            id_col=ID_COL,
        )
    else:
        logging.info("[DRY-RUN] Would run label_singletons_as_uc(%s → %s)", dest_cluster, dest_uc)

    # STEP 3 — cleptr run: update lineage-level nomenclature
    logging.info("[STEP 3] Updating lineage-level cleptr database (Tx:12)")
    validate_json(possible_clusters)
    if not dry_run:
        backup_json(possible_samples, backup_dir=backup_dir)
        backup_json(possible_clusters, backup_dir=backup_dir)
    run_cmd(
        f"cleptr run "
        f"-i snp_clusters_uc.txt.{mdate} "
        f"-s possible_samples.json "
        f"-c possible_clusters.json "
        f"--cluster_col {CLUSTER_COL_LINEAGE} "
        f"--id_col {ID_COL}",
        step=f"cleptr-run Lineage_{lineage}",
        cwd=lineage_dir,
        dry_run=dry_run,
    )

    # STEP 4 — cleptr report
    logging.info("[STEP 4] Generating cleptr report")
    run_cmd(
        f"cleptr report "
        f"-s possible_samples.json "
        f"-p Lineage_{lineage}_{mdate}_report "
        f"--id_col {ID_COL}",
        step=f"cleptr-report Lineage_{lineage}",
        cwd=lineage_dir,
        dry_run=dry_run,
    )

    # STEP 5 — High-res cluster updates (was make_high.py)
    logging.info("[STEP 5] Updating high-resolution cluster databases (Tx:5)")
    if dry_run:
        logging.info("[DRY-RUN] Would run high-res cluster updates using %s", dest_uc)
    else:
        run_high_res_clusters(
            uc_cluster_file=dest_uc,
            possible_clusters_json=possible_clusters,
            high_col=CLUSTER_COL_HIGH,
            id_col=ID_COL,
            lineage_db_dir=lineage_dir,
            backup_dir=backup_dir,
            dry_run=dry_run,
        )

    logging.info("Lineage %s completed successfully.", lineage)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Entry point for the MTB cleptr reporting pipeline."""
    args = parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level, format=LOG_FORMAT, datefmt=DATE_FORMAT)

    lineage_list = [l.strip() for l in args.lineages.split(",") if l.strip()]
    run_ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    try:
        logging.info("MTB cleptr pipeline starting")
        logging.info("Date suffix      : %s", args.mdate)
        logging.info("Lineages         : %s", lineage_list)
        logging.info("Analysis path    : %s", args.analysis_path)
        logging.info("cleptr DB path   : %s", args.cleptr_db_path)
        logging.info("Run timestamp    : %s", run_ts)
        logging.info("Dry-run mode     : %s", args.dry_run)

        failed_lineages = []

        for lineage in lineage_list:
            try:
                # Pre-flight: verify all required inputs before touching anything
                pre_flight_check(
                    lineage=lineage,
                    mdate=args.mdate,
                    analysis_path=args.analysis_path,
                    cleptr_db_path=args.cleptr_db_path,
                )
                process_lineage(
                    lineage=lineage,
                    mdate=args.mdate,
                    analysis_path=args.analysis_path,
                    cleptr_db_path=args.cleptr_db_path,
                    run_ts=run_ts,
                    dry_run=args.dry_run,
                )
            except Exception as exc:
                logging.error(
                    "Lineage %s FAILED: %s — continuing with remaining lineages.",
                    lineage, exc,
                )
                if args.verbose:
                    logging.exception("Full traceback:")
                failed_lineages.append(lineage)

        if failed_lineages:
            logging.error(
                "Pipeline completed with failures in lineage(s): %s",
                ", ".join(failed_lineages),
            )
            sys.exit(1)

        logging.info("All lineages processed successfully. Done.")

    except Exception as exc:
        logging.error("Fatal error: %s", exc, exc_info=args.verbose)
        sys.exit(1)


if __name__ == "__main__":
    main()

