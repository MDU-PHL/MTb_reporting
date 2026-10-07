"""
update_sheets.py
----------------
Append new TB isolate records from an epi-supplied Excel file into the two
master surveillance spreadsheets (tb_metadata.xlsx and TBsharepoint.xlsx).

Handles input files where column headers may differ from the internal naming
convention by applying an explicit rename map before any merging occurs,
making the script fully column-order and column-name agnostic.

Produces a detailed audit log of:
  - Column mapping applied
  - Rows / columns added to each output file
  - Final dimensions of both output files
"""

import sys
import logging
import argparse

import pandas as pd


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

METADATA_PATH   = "/home/mdu/analysis/surveillance/MTB_report/tb_metadata.xlsx"
SHAREPOINT_PATH = "/home/mdu/analysis/surveillance/MTB_report/TBsharepoint.xlsx"

# Maps raw header names in the supplier's input file -> internal column names.
# Order does not matter; only header labels are used.
COLUMN_RENAME_MAP = {
    "Batch #":           "Batch #",
    "Isolate #":         "Isolate #",
    "Submitters ID":     "VIDRL Lab No.",
    "Date coll":         "Specimen collection date",
    "MDU sample ID":     "MDU ID",
    "2x2":               "2x2",
    "Sex":               "Gender",
    "DOB":               "DOB",
    "REFERENCE_NUMBER":  "REFERENCE_NUMBER",
    "LAB":               "lab",
    "EVENT_ID":          "PHESS ID",
    "EVENT_DATE":        "EVENT_DATE",
    "CALCULATED_ONSET":  "CALCULATED_DATE_OF_ONSET",
    "LGA":               "LGA",
    "MANIFESTATION":     "MANIFESTATION",
    "COB":               "COUNTRY_OF_BIRTH",
    "YEAR_OF_ARRIVAL":   "YEAR_OF_ARRIVAL",
    "ASSIGNED_TO":       "ASSIGNED_TO",
}

DATE_COLUMNS = ["CALCULATED_DATE_OF_ONSET", "DOB", "Specimen collection date"]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    epilog = """
Examples:
  python update_sheets.py tb_isolates_metadata_20240901.xlsx
  python update_sheets.py tb_isolates_metadata_20240901.xlsx --verbose
  python update_sheets.py tb_isolates_metadata_20240901.xlsx -m /custom/path/tb_metadata.xlsx
    """
    parser = argparse.ArgumentParser(
        description="Append new TB isolate records to tb_metadata and TBsharepoint master files.",
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "file",
        type=str,
        help="Path to the epi-supplied input Excel file.",
    )
    parser.add_argument(
        "--metadata", "-m",
        type=str,
        default=METADATA_PATH,
        help=f"Path to the tb_metadata master Excel file (default: {METADATA_PATH}).",
    )
    parser.add_argument(
        "--sharepoint", "-s",
        type=str,
        default=SHAREPOINT_PATH,
        help=f"Path to the TBsharepoint master Excel file (default: {SHAREPOINT_PATH}).",
    )
    parser.add_argument(
        "--out-metadata",
        type=str,
        default="tb_metadata.xlsx",
        help="Output filename for the updated metadata file (default: tb_metadata.xlsx).",
    )
    parser.add_argument(
        "--out-sharepoint",
        type=str,
        default="TBsharepoint.xlsx",
        help="Output filename for the updated sharepoint file (default: TBsharepoint.xlsx).",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable DEBUG-level logging output.",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="[%(asctime)s] <%(levelname)s> %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def log_dimensions(label: str, df: pd.DataFrame) -> None:
    logging.info(f"  {label}: {df.shape[0]} rows x {df.shape[1]} columns")


def rename_columns(isolates: pd.DataFrame) -> pd.DataFrame:
    """Apply COLUMN_RENAME_MAP to the isolates DataFrame.

    Only maps columns that are present in the input; unknown columns are
    passed through unchanged. Logs a warning for any expected input columns
    that are missing.
    """
    present     = set(isolates.columns)
    expected    = set(COLUMN_RENAME_MAP.keys())
    missing     = expected - present
    unexpected  = present - expected

    if missing:
        logging.warning(
            f"The following expected input columns were NOT found and will be skipped: {sorted(missing)}"
        )
    if unexpected:
        logging.debug(
            f"The following input columns have no rename mapping and will be kept as-is: {sorted(unexpected)}"
        )

    # Only rename columns that are actually present
    active_map = {k: v for k, v in COLUMN_RENAME_MAP.items() if k in present}
    logging.debug(f"Applying column rename map ({len(active_map)} mappings):")
    for src, dst in active_map.items():
        logging.debug(f"  '{src}' -> '{dst}'")

    return isolates.rename(columns=active_map)


def format_dates(isolates: pd.DataFrame) -> pd.DataFrame:
    """Convert date columns to DD/MM/YYYY strings."""
    for col in DATE_COLUMNS:
        if col in isolates.columns:
            isolates[col] = pd.to_datetime(isolates[col], errors="coerce").dt.strftime("%d/%m/%Y")
            logging.debug(f"  Formatted date column: '{col}'")
        else:
            logging.warning(f"  Date column '{col}' not present after renaming -- skipped.")
    return isolates


def derive_name_columns(isolates: pd.DataFrame) -> pd.DataFrame:
    """Derive 'Surname 2x' and 'First Name 2x' from the '2x2' column."""
    if "2x2" not in isolates.columns:
        logging.warning("Column '2x2' not found -- skipping name derivation.")
        return isolates
    isolates["name"] = isolates["2x2"].str[:2] + ":" + isolates["2x2"].str[2:]
    isolates[["Surname 2x", "First Name 2x"]] = (
        isolates["name"].str.split(":", n=1, expand=True)
    )
    logging.debug("Derived 'Surname 2x' and 'First Name 2x' from '2x2'.")
    return isolates


def validate_row_count(label: str, before: int, after: int, n_new: int) -> bool:
    expected = before + n_new
    if after != expected:
        logging.error(
            f"[{label}] Row count mismatch! Expected {expected} "
            f"({before} existing + {n_new} new) but got {after}."
        )
        return False
    return True


def audit_append(label: str, original: pd.DataFrame, updated: pd.DataFrame, isolates: pd.DataFrame) -> None:
    """Log a detailed audit of what changed between original and updated DataFrames."""
    rows_added   = len(updated) - len(original)
    cols_before  = set(original.columns)
    cols_after   = set(updated.columns)
    cols_added   = cols_after - cols_before
    cols_removed = cols_before - cols_after

    logging.info(f"-- Audit: {label} " + "-" * (50 - len(label)))
    logging.info(f"  Rows before  : {len(original)}")
    logging.info(f"  Rows added   : {rows_added}")
    logging.info(f"  Rows after   : {len(updated)}")
    logging.info(f"  Cols before  : {len(cols_before)}")
    logging.info(f"  Cols after   : {len(cols_after)}")
    if cols_added:
        logging.info(f"  Cols added   : {sorted(cols_added)}")
    if cols_removed:
        logging.warning(f"  Cols removed (in master but absent in new data): {sorted(cols_removed)}")

    shared_cols = sorted(cols_before & set(isolates.columns))
    logging.debug(f"  Shared columns used in append ({len(shared_cols)}): {shared_cols}")

    logging.info(f"  Preview of {rows_added} newly appended row(s):\n{updated.tail(rows_added).to_string(index=False)}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    args = parse_args()
    setup_logging(args.verbose)

    logging.info("=" * 60)
    logging.info("update_sheets.py -- TB Surveillance Master File Updater")
    logging.info("=" * 60)
    logging.info(f"Input file        : {args.file}")
    logging.info(f"Metadata path     : {args.metadata}")
    logging.info(f"Sharepoint path   : {args.sharepoint}")
    logging.info(f"Output metadata   : {args.out_metadata}")
    logging.info(f"Output sharepoint : {args.out_sharepoint}")

    # --- Load input ---
    logging.info("Loading input file ...")
    isolates = pd.read_excel(args.file)
    logging.info(f"  Loaded {len(isolates)} new isolate(s) with {len(isolates.columns)} column(s).")
    logging.debug(f"  Input columns: {list(isolates.columns)}")

    # --- Rename columns (order-agnostic) ---
    logging.info("Applying column rename map ...")
    isolates = rename_columns(isolates)

    # --- Derive name columns ---
    logging.info("Deriving name columns from '2x2' ...")
    isolates = derive_name_columns(isolates)

    # --- Format dates ---
    logging.info("Formatting date columns ...")
    isolates = format_dates(isolates)

    logging.debug(f"  Final isolates columns after processing: {list(isolates.columns)}")

    # --- Load master files ---
    logging.info("Loading master files ...")
    metadata = pd.read_excel(args.metadata)
    sharepoint = pd.read_excel(
        args.sharepoint,
        parse_dates=["DOB", "Specimen collection date"],
    )
    logging.info(f"  tb_metadata  : {len(metadata)} rows x {len(metadata.columns)} columns")
    logging.info(f"  TBsharepoint : {len(sharepoint)} rows x {len(sharepoint.columns)} columns")

    # --- Append to tb_metadata ---
    logging.info("Appending to tb_metadata ...")
    final_meta = pd.concat([metadata, isolates], join="inner").fillna("NA")
    audit_append("tb_metadata", metadata, final_meta, isolates)
    ok_meta = validate_row_count("tb_metadata", len(metadata), len(final_meta), len(isolates))

    # --- Append to TBsharepoint ---
    logging.info("Appending to TBsharepoint ...")
    shared_cols = list(set(sharepoint.columns) & set(isolates.columns))
    logging.debug(f"  Shared columns for sharepoint append: {sorted(shared_cols)}")
    final_sp = pd.concat(
        [sharepoint, isolates[shared_cols]], ignore_index=True
    ).fillna("NA")
    audit_append("TBsharepoint", sharepoint, final_sp, isolates)
    ok_sp = validate_row_count("TBsharepoint", len(sharepoint), len(final_sp), len(isolates))

    # --- Save outputs ---
    if ok_meta and ok_sp:
        logging.info("Saving updated files ...")
        final_meta.to_excel(args.out_metadata,   index=False)
        final_sp.to_excel(args.out_sharepoint, index=False)
        logging.info(f"  Saved: {args.out_metadata}")
        logging.info(f"  Saved: {args.out_sharepoint}")
    else:
        logging.error("One or more output files were NOT saved due to row-count mismatches. Review errors above.")
        sys.exit(1)

    # --- Final dimensions ---
    logging.info("-" * 60)
    logging.info("Final dimensions of output files:")
    log_dimensions(args.out_metadata,   final_meta)
    log_dimensions(args.out_sharepoint, final_sp)
    logging.info("-" * 60)
    logging.info(f"Done. {len(isolates)} new isolate(s) appended to both master files.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logging.exception(f"Fatal error: {exc}")
        sys.exit(1)
