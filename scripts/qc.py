"""QC script for TB lineage checking.

Reads a per-batch CSV produced by the pipeline, applies a lineage
pass/fail filter, appends results to a running lineage_checked.csv log,
and runs `mdu reads` / `mdu contigs` for each passing non-La lineage.

Usage examples
--------------
    python3 qc.py 2026-09-14 tbtamr.csv
    python3 qc.py --date 2026-09-14 --input tbtamr.csv
    python3 qc.py -d 2026-09-14 -i tbtamr.csv --verbose

Version
-------
last updated: 2026-09-16
"""

import argparse
import logging
import pathlib
import subprocess
import sys

import pandas as pd


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LOG_FMT = "[%(asctime)s] <%(levelname)s> %(message)s"
LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"

LINEAGE_LOG = pathlib.Path("lineage_checked.csv")
LINEAGE_COLS = ["Seq_ID", "Species", "Phylogenetic lineage", "pass_lineage"]


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="QC filter for TB lineage reports.",
        epilog=(
            "Examples:\n"
            "  python3 qc.py 2026-09-14 tbtamr.csv\n"
            "  python3 qc.py --date 2026-09-14 --input tbtamr.csv\n"
            "  python3 qc.py -d 2026-09-14 -i tbtamr.csv --verbose\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-d", "--date",
        dest="date",
        help="Date identifier used in the output filename, e.g. 2026-09-14.",
    )
    parser.add_argument(
        "-i", "--input",
        dest="input",
        help="Path to the per-batch CSV file (e.g. tbtamr.csv).",
    )
    parser.add_argument(
        "date_pos",
        nargs="?",
        metavar="DATE",
        help="Date identifier (positional alternative to --date).",
    )
    parser.add_argument(
        "input_pos",
        nargs="?",
        metavar="INPUT",
        help="Input CSV file path (positional alternative to --input).",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable DEBUG-level logging.",
    )
    args = parser.parse_args()

    # Consolidate positional and optional arguments for seamless backwards compatibility
    args.date = args.date or args.date_pos
    args.input = args.input or args.input_pos

    if not args.date or not args.input:
        parser.error(
            "Both date and input file are required (provide as positional arguments or via --date / --input)."
        )

    return args


# ---------------------------------------------------------------------------
# Logic
# ---------------------------------------------------------------------------

def lineage_pass(lineage: str) -> str:
    """Return 'fail' if the lineage string is ambiguous or missing, else 'pass'."""
    if "Not" in lineage or ";" in lineage:
        return "fail"
    return "pass"


def run(cmd: str) -> None:
    """Run a shell command, logging it at DEBUG level."""
    logging.debug("Running: %s", cmd)
    subprocess.run(cmd, shell=True, check=True)


def main() -> None:
    args = parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format=LOG_FMT, datefmt=LOG_DATEFMT)

    logging.info("Date: %s | Input: %s", args.date, args.input)

    # --- Load inputs --------------------------------------------------------
    log_df = pd.read_csv(LINEAGE_LOG)
    batch_df = pd.read_csv(args.input)
    batch_df.rename(columns={"MDU sample ID": "Seq_ID"}, inplace=True)

    # --- Apply lineage filter -----------------------------------------------
    batch_df["pass_lineage"] = batch_df["Phylogenetic lineage"].apply(lineage_pass)

    failing = batch_df[batch_df["pass_lineage"] == "fail"]
    logging.info("%d sample(s) failed lineage check.", len(failing))
    if not failing.empty:
        logging.debug("Failing samples:\n%s", failing.to_string(index=False))

    # --- Write per-batch CSV -------------------------------------------------
    batch_out = pathlib.Path(f"lineage_checked_{args.date}.csv")
    batch_df.to_csv(batch_out, index=False)
    logging.info("Wrote per-batch CSV: %s", batch_out)

    # --- Append to running log -----------------------------------------------
    common_cols = log_df.columns.intersection(batch_df.columns)
    log_df = pd.concat([log_df, batch_df[common_cols]], ignore_index=True)
    log_df = log_df[LINEAGE_COLS]
    log_df.to_csv(LINEAGE_LOG, index=False)
    logging.info("Updated lineage log: %s", LINEAGE_LOG)

    # --- Run MDU commands for passing non-La lineages --------------------
    passing_df = batch_df[batch_df["pass_lineage"] == "pass"]
    logging.info("%d sample(s) passed lineage check.", len(passing_df))

    for lineage in passing_df["Phylogenetic lineage"].unique():
        lineage_dir = "_".join(lineage.split())

        if "La" in lineage:
            logging.debug("Skipping La lineage: %s", lineage)
            continue

        logging.info("Processing lineage: %s", lineage)
        isolates = list(passing_df[passing_df["Phylogenetic lineage"] == lineage]["Seq_ID"].unique())

        list_file = pathlib.Path(f"{lineage_dir}.list")
        list_file.write_text("\n".join(isolates))

        run(f"mkdir -p {lineage_dir}")
        # run(f"mdu reads --idfile {lineage_dir}.list >> {lineage_dir}/isolates.tab")
        # change 1.trim to 2.trim in column 2, and 2.trim to 1.trim in column 3 FLAG: interim
        run(f"mdu reads --idfile {lineage_dir}.list | awk 'BEGIN{{OFS=FS=\"\\t\"}} {{gsub(\"2\\\\.trim\",\"1.trim\",$2); gsub(\"1\\\\.trim\",\"2.trim\",$3); print}}' >> {lineage_dir}/isolates.tab")

        run(f"mdu contigs --idfile {lineage_dir}.list >> {lineage_dir}/contigs.tab")

    logging.info("Done.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logging.critical("Fatal error: %s", exc)
        sys.exit(1)
