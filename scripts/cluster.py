#!/usr/bin/env python3
"""
Cluster sequences and isolates based on pairwise distance matrices using
hierarchical agglomerative single-linkage clustering at configurable thresholds.

Version
-------
last updated: 2026-09-17
"""

import argparse
import logging
import sys
from typing import List, Tuple

import numpy as np
import pandas as pd
from sklearn.cluster import AgglomerativeClustering

# Constants
DEFAULT_DISTANCE_FILE = "report/distances.tab"
DEFAULT_THRESHOLDS = "1,2,5,10,20"
DEFAULT_OUTPUT = "clusters.csv"
LOG_FORMAT = "[%(asctime)s] <%(levelname)s> %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Cluster sequences based on pairwise distance matrices at various thresholds.",
        epilog="""Usage examples:
  # Match legacy cluster.py output (tab-delimited, thresholds 5 and 12, 0-indexed labels):
  python3 cluster_new.py -d distances.tab -t 5,12 -o snp_clusters.txt.2026-09-14 --tab --zero-indexed

  # Standard run with 1-based cluster labels in tab-delimited format:
  python3 cluster_new.py -d distances.tab -t 5,12 -o snp_clusters.txt.2026-09-14 -b

  # Default thresholds with comma-delimited CSV output and verbose logging:
  python3 cluster_new.py -d report/distances.tab -o clusters.csv -v
""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-d",
        "--distance-matrix",
        "--path_to_distance_file",
        dest="distance_matrix",
        type=str,
        default=DEFAULT_DISTANCE_FILE,
        help=f"Path to the distance matrix file (default: {DEFAULT_DISTANCE_FILE})",
    )
    parser.add_argument(
        "-t",
        "--thresholds",
        type=str,
        default=DEFAULT_THRESHOLDS,
        help=f"Comma-separated list of distance thresholds for clustering (default: {DEFAULT_THRESHOLDS})",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default=DEFAULT_OUTPUT,
        help=f"Name of the output file (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "-b",
        "--tab",
        action="store_true",
        default=False,
        help="Write output as tab-delimited text (TSV) instead of comma-delimited (CSV)",
    )
    parser.add_argument(
        "-z",
        "--zero-indexed",
        action="store_true",
        default=False,
        help="Use 0-based cluster numbering (0, 1, ...) matching legacy cluster.py instead of default 1-based (1, 2, ...)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        default=False,
        help="Enable verbose DEBUG logging",
    )

    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(1)

    return parser.parse_args()


def load_distance_matrix(file_path: str) -> Tuple[List[str], np.ndarray]:
    """
    Load isolate IDs and pairwise distance matrix from a tab-separated file.

    Parameters
    ----------
    file_path : str
        Path to the tab-delimited distance file.

    Returns
    -------
    Tuple[List[str], np.ndarray]
        List of isolate names and precomputed distance matrix as float ndarray.
    """
    logging.debug("Reading distance matrix from: %s", file_path)
    isolate_ids = []
    matrix_rows = []

    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.read().strip().split("\n")

    if not lines or len(lines) < 2:
        raise ValueError(f"Distance file '{file_path}' is empty or missing data rows.")

    for line in lines[1:]:
        parts = line.split("\t")
        isolate_ids.append(parts[0])
        matrix_rows.append(parts[1:])

    distance_matrix = np.array(matrix_rows, dtype=float)
    logging.debug("Loaded %d isolates, matrix shape %s", len(isolate_ids), distance_matrix.shape)
    return isolate_ids, distance_matrix


def run_clustering(
    isolate_ids: List[str],
    distance_matrix: np.ndarray,
    thresholds: List[int],
    zero_indexed: bool = False,
) -> pd.DataFrame:
    """
    Perform hierarchical single-linkage clustering across specified thresholds.

    Parameters
    ----------
    isolate_ids : List[str]
        List of isolate identifiers.
    distance_matrix : np.ndarray
        Pairwise distance matrix.
    thresholds : List[int]
        Distance thresholds at which to cut clusters.
    zero_indexed : bool
        If True, labels start from 0 (legacy cluster.py behavior); otherwise start from 1.

    Returns
    -------
    pd.DataFrame
        DataFrame with isolate IDs and cluster assignments per threshold.
    """
    result_df = pd.DataFrame()
    label_offset = 0 if zero_indexed else 1

    for n in thresholds:
        logging.debug("Clustering at distance threshold: %d (offset: +%d)", n, label_offset)
        kwargs = {
            "n_clusters": None,
            "linkage": "single",
            "distance_threshold": n,
        }
        try:
            clustering = AgglomerativeClustering(metric="precomputed", **kwargs).fit(distance_matrix)
        except TypeError:
            # Fallback for scikit-learn versions < 1.2
            clustering = AgglomerativeClustering(affinity="precomputed", **kwargs).fit(distance_matrix)

        labels = clustering.labels_ + label_offset
        num_clusters = len(np.unique(labels))
        logging.info("Threshold %d: identified %d distinct clusters", n, num_clusters)

        df = pd.DataFrame(data={"Seq_ID": isolate_ids, f"Tx:{n}": labels})
        if result_df.empty:
            result_df = df
        else:
            result_df = result_df.merge(df, on="Seq_ID")

    return result_df


def save_clusters(df: pd.DataFrame, output_path: str, tab_delimited: bool = False) -> None:
    """
    Save clustered results to file.

    Parameters
    ----------
    df : pd.DataFrame
        Clustering results.
    output_path : str
        Target output file path.
    tab_delimited : bool
        Whether to format output as tab-separated instead of comma-separated.
    """
    delimiter = "\t" if tab_delimited else ","
    format_name = "tab-delimited (TSV)" if tab_delimited else "comma-delimited (CSV)"
    logging.debug("Saving %d rows to '%s' as %s", len(df), output_path, format_name)
    df.to_csv(output_path, sep=delimiter, index=False)


def main() -> None:
    """Main execution function."""
    args = parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level, format=LOG_FORMAT, datefmt=DATE_FORMAT)

    try:
        thresholds = [int(t.strip()) for t in args.thresholds.split(",") if t.strip()]
        if not thresholds:
            raise ValueError("No valid integer thresholds provided.")

        logging.info("Starting sequence clustering")
        logging.info("Distance matrix file : %s", args.distance_matrix)
        logging.info("Thresholds           : %s", thresholds)
        logging.info("Output destination   : %s", args.output)
        logging.info("Format               : %s", "tab-delimited" if args.tab else "comma-delimited")
        logging.info("Index numbering      : %s", "0-based (legacy)" if args.zero_indexed else "1-based")

        isolate_ids, distance_matrix = load_distance_matrix(args.distance_matrix)
        clusters_df = run_clustering(
            isolate_ids=isolate_ids,
            distance_matrix=distance_matrix,
            thresholds=thresholds,
            zero_indexed=args.zero_indexed,
        )

        save_clusters(clusters_df, args.output, tab_delimited=args.tab)
        logging.info("Successfully wrote clustering results to %s", args.output)
        logging.info("Done.")

    except Exception as err:
        logging.error("Fatal error during clustering execution: %s", err, exc_info=args.verbose)
        sys.exit(1)


if __name__ == "__main__":
    main()