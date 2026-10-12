"""
MTB_new_report.py
-----------------
Generate MTB surveillance reports from cleptr output.

Workflow:
  1. Load TBsharepoint.xlsx + tb_metadata.xlsx + lineage_checked.csv
  2. Build epi table and draw monthly epicurve  --> epi.png
  3. Load per-lineage cluster CSVs from cleptr_db (Lineage 1-4) and log exact paths
  4. Renumber subclusters sequentially (1, 2, 3 ... instead of raw IDs)
  5. Write cluster_report_<date>.csv, new_summary_table.csv, Uncluster_summary.csv
  6. For each cluster that contains >= 1 new isolate:
       - Lineage_X_<cluster>.csv            (epi detail; all cluster members, new + historical)
       - Lineage_X_<cluster>_dist_summary.csv
       - Lineage_<lin>_<cluster>_his.png    (Altair timeline chart, PNG)
       - <cluster>_<lineage>_tree.svg / .png
"""

import logging
import os
import sys
import subprocess
import argparse

import pandas
import numpy
import altair as alt
alt.data_transformers.disable_max_rows()
import toytree
import toyplot
import toyplot.svg
import toyplot.png
from svglib.svglib import svg2rlg
from reportlab.graphics import renderPM

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    format="[%(asctime)s] <%(levelname)s> %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
REPORT_FOLDER = "/home/mdu/analysis/surveillance/MTB_cleptr/cleptr_db"
ANALYSIS_FOLDER = "/home/mdu/analysis/surveillance/tb_dev"
LINEAGES = ["1", "2", "3", "4"]

EPI_COLORS = ["#fcba03", "#9771b0", "#69aed6", "#c95975", "#74d669", "#d6851c", "#42f5c8"]
EPI_DOMAIN = ["Lineage 1", "Lineage 2", "Lineage 3", "Lineage 4", "Lineage 5", "Lineage 6", "Lineage 9"]

TIP_DICT = {
    "1": "#4c78a8",
    "2": "#f58518",
    "3": "#e45756",
    "PR": "#84dae0",
    "new": "#e33f22",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def bash_command(cmd):
    p = subprocess.Popen(cmd, shell=True)
    while True:
        return_code = p.poll()
        if return_code is not None:
            break


def save_altair_chart(chart, png_path: str) -> None:
    """Save an Altair chart as PNG using vl-convert-python.

    Uses vl_convert.vegalite_to_png() which converts the Vega-Lite JSON spec
    directly to PNG bytes using a self-contained Rust renderer — no vega-cli,
    no SVG intermediate, no svglib/renderPM involved.

    Requires: pip install vl-convert-python

    Falls back to saving .html with a warning if vl_convert is not available.

    Args:
        chart:    Altair Chart object to save.
        png_path: Output PNG path.
    """
    try:
        import vl_convert as vlc
    except ImportError:
        html_path = png_path.replace(".png", ".html")
        chart.save(html_path)
        log.warning(
            f"vl-convert-python not installed — saved HTML instead: {html_path}. "
            f"Run: pip install vl-convert-python"
        )
        return

    png_bytes = vlc.vegalite_to_png(vl_spec=chart.to_json(), scale=2)
    with open(png_path, "wb") as f:
        f.write(png_bytes)
    log.info(f"Saved chart: {png_path}")


def ck_files():
    """Abort early if required input files are missing."""
    if not os.path.exists("../TBsharepoint.xlsx"):
        log.error("Please upload TBsharepoint.xlsx — process terminated.")
        sys.exit(1)
    if not os.path.exists("new_isolates.txt"):
        log.error("Please create new_isolates.txt — process terminated.")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate MTB reports from cleptr output.",
        epilog=(
            "Examples:\n"
            "  python3 MTB_new_report.py -d 2025-09-01\n"
            "  python3 MTB_new_report.py --date 2025-09-01 --verbose\n"
            "  python3 MTB_new_report.py -d 2025-09-01 -c /path/to/cleptr_db -a /path/to/tb_dev -l 1 2 3 4"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-d", "--date",
        dest="report_date",
        default="2025-08-19",
        help="Report date suffix (YYYY-MM-DD). Used to read lineage files named lineage_X.<date>.csv",
    )
    parser.add_argument(
        "-c", "--cleptr-db-path", "--report-folder",
        dest="cleptr_db_path",
        default=REPORT_FOLDER,
        help=f"Path to cleptr_db folder containing Lineage_X subdirectories (default: {REPORT_FOLDER}).",
    )
    parser.add_argument(
        "-a", "--analysis-path",
        dest="analysis_path",
        default=ANALYSIS_FOLDER,
        help=f"Path to analysis folder containing lineage_checked.csv and per-lineage report directories (default: {ANALYSIS_FOLDER}).",
    )
    parser.add_argument(
        "-l", "--lineages",
        dest="lineages",
        nargs="+",
        default=LINEAGES,
        help=f"List of lineages to process (default: {' '.join(LINEAGES)}).",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        default=False,
        help="Enable DEBUG-level logging.",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    args = parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    report_date = args.report_date
    cleptr_db_path = args.cleptr_db_path
    analysis_path = args.analysis_path

    lineages = []
    for item in args.lineages:
        if "," in item:
            lineages.extend([x.strip() for x in item.split(",") if x.strip()])
        else:
            lineages.append(item.strip())

    log.info(f"Starting MTB_new_report.py | report_date={report_date}")
    log.debug(f"cleptr_db_path={cleptr_db_path}")
    log.debug(f"analysis_path={analysis_path}")
    log.debug(f"lineages={lineages}")

    # -----------------------------------------------------------------------
    # 0. Pre-flight checks
    # -----------------------------------------------------------------------
    ck_files()

    # -----------------------------------------------------------------------
    # 1. Load sharepoint + metadata
    # -----------------------------------------------------------------------
    log.info("Loading TBsharepoint.xlsx ...")
    sharepoint = pandas.read_excel("../TBsharepoint.xlsx")
    sharepoint["PHESS ID"] = sharepoint["PHESS ID"].apply(
        lambda x: int(x) if f"{x}" != "nan" else ""
    )
    # Added VIDRL ID to report as per Sally's request 20240105
    sharepoint["VIDRL Lab No."] = sharepoint["VIDRL Lab No."].apply(
        lambda x: str(x) if f"{x}" != "nan" else ""
    )
    sharepoint["Specimen collection date"] = sharepoint["Specimen collection date"].apply(
        lambda x: str(x).strip("*")
    )
    sharepoint["DOB"] = sharepoint["DOB"].apply(lambda x: str(x).strip("* "))
    sharepoint["Collection date"] = pandas.to_datetime(
        sharepoint["Specimen collection date"], dayfirst=True
    )
    sharepoint["DOB"] = pandas.to_datetime(sharepoint["DOB"])
    sharepoint = sharepoint.rename(columns={"MDU ID": "Seq_ID"})

    log.info("Loading tb_metadata.xlsx ...")
    metainfo = pandas.read_excel("../tb_metadata.xlsx")
    sharepoint = sharepoint.merge(metainfo, how="left", on="PHESS ID")

    # -----------------------------------------------------------------------
    # 2. Load new isolates list
    # -----------------------------------------------------------------------
    new_isos = []
    with open("new_isolates.txt", "r") as mynew:
        for line in mynew:
            mid = line.strip()
            if len(mid) > 0:
                new_isos.append(mid)
    log.info(f"New isolates in this report: {len(new_isos)}")

    # -----------------------------------------------------------------------
    # 3. Load lineage_checked.csv and merge
    # -----------------------------------------------------------------------
    lins_path = f"{analysis_path}/lineage_checked.csv"
    log.info(f"Loading lineage data: {lins_path}")
    lins = pandas.read_csv(lins_path)
    lins = lins.rename(columns={"Seq_id": "Seq_ID"})

    tab_lin = sharepoint.merge(lins, how="left")
    tab = tab_lin.drop_duplicates(subset="Seq_ID", keep="first")
    tab.to_csv("epi.csv", index=None)
    tab = tab[~tab["Seq_ID"].isna()]

    # -----------------------------------------------------------------------
    # 4. Build epi table and epicurve  -->  epi.png
    # -----------------------------------------------------------------------
    today = pandas.Timestamp.today().normalize()

    for_epi = tab[~tab["Species"].isna()]

    # Fail fast if there are rows with collection date in the future — indicates data entry errors
    future_rows = for_epi[for_epi["Collection date"] > today]
    if len(future_rows) > 0:
        log.error(
            f"{len(future_rows)} isolate(s) have a collection date in the future "
            f"(after {today.date()})."
        )
        for _, r in future_rows.iterrows():
            log.error(f"  Seq_ID={r['Seq_ID']}  Collection date={r['Collection date'].date()}")
        log.error("Please check TBsharepoint.xlsx for data entry errors and fix them before proceeding.")
        sys.exit(1)

    for_epi = for_epi[
        (for_epi["Collection date"] > "2017-01-01")
        & (for_epi["pass_lineage"] == "pass")
        & (~for_epi["Phylogenetic lineage"].str.contains("La"))
    ]
    inside_collection_day_list = for_epi.Seq_ID.tolist()
    log.debug(f"Isolates inside collection day list: {len(inside_collection_day_list)}")


    mltd = (
        for_epi.groupby(
            [pandas.Grouper(key="Collection date", freq="1M"), "Phylogenetic lineage"]
        )
        .agg("count")
        .reset_index()
    )
    mltd_test = (
        for_epi.groupby(
            [pandas.Grouper(key="Collection date", freq="1M"), "Seq_ID"]
        )
        .agg("count")
        .reset_index()
    )
    mltd_test.to_csv("error_count.csv", index=None)
    mltd.to_csv("epi_count.csv", index=None)

    log.info("Drawing epicurve ...")
    epi_chart = (
        alt.Chart(mltd)
        .mark_bar()
        .encode(
            x=alt.X(
                "yearmonth(Collection date)",
                title="Collection date",
                axis=alt.Axis(labelAngle=-90),
            ),
            y=alt.Y("Seq_ID", title="Count"),
            color=alt.Color(
                "Phylogenetic lineage",
                scale=alt.Scale(domain=EPI_DOMAIN, range=EPI_COLORS),
            ),
        )
        .properties(width=700, height=300)
    )
    save_altair_chart(epi_chart, "epi.png")

    # -----------------------------------------------------------------------
    # 5. Load cleptr cluster CSVs — log exact file paths
    # -----------------------------------------------------------------------
    ct = pandas.DataFrame()
    for lin in lineages:
        csv_path = f"{cleptr_db_path}/Lineage_{lin}/lineage_{lin}.{report_date}.csv"
        log.info(f"Loading cleptr cluster file: {csv_path}")
        if not os.path.exists(csv_path):
            log.warning(f"Cluster file not found, skipping: {csv_path}")
            continue
        tmp = pandas.read_csv(csv_path)
        tmp["Lineage"] = f"L{lin}"
        ct = tmp if ct.empty else pandas.concat([ct, tmp])

    ct = ct.rename(columns={"ID": "Seq_ID"})

    # -----------------------------------------------------------------------
    # 6. Renumber subclusters: raw IDs -> sequential integers per cluster
    # -----------------------------------------------------------------------
    m_ids = []
    cluster_dict = {}
    id_info = []
    title = ["Seq_ID", "Cluster_poss", "Cluster_highly", "Cluster_ID"]
    uncluster_list = []

    for index, row in ct.iterrows():
        m_id = row["Seq_ID"]
        cluster = row["Cluster_poss"]
        sub_cluster = row["Cluster_highly"]
        m_ids.append(m_id)

        if cluster == "UC":
            id_info.append([m_id, cluster, sub_cluster, f"{row['Lineage']}-{row['Cluster_ID']}"])
            uncluster_list.append(m_id)
        elif sub_cluster == "UC":
            id_info.append([m_id, cluster, "PR", f"{row['Lineage']}-Clst-{cluster}-PR"])
        else:
            cluster_key = f"{row['Lineage']}_{cluster}"
            sub_dict = cluster_dict.get(cluster_key, {})
            new_name = sub_dict.get(sub_cluster, "x")
            if new_name == "x":
                names = list(sub_dict.values())
                if len(names) == 0:
                    new_name = "1"
                else:
                    names.sort()
                    new_name = str(int(names[-1]) + 1)
                sub_dict[sub_cluster] = new_name
            cluster_dict[cluster_key] = sub_dict
            id_info.append([m_id, cluster, new_name, f"{row['Lineage']}-Clst-{cluster}-{new_name}"])

    new_ct = pandas.DataFrame(id_info, columns=title)
    ct = new_ct.copy()

    # -----------------------------------------------------------------------
    # 7. Merge cluster info into main table and write full cluster report
    # -----------------------------------------------------------------------
    tab = tab.merge(ct, how="left")
    tab = tab[
        [
            "Seq_ID", "PHESS ID", "VIDRL Lab No.", "Surname 2x", "First Name 2x",
            "DOB", "Gender", "Collection date", "Species", "Phylogenetic lineage",
            "Cluster_poss", "Cluster_highly", "Cluster_ID", "MANIFESTATION",
            "CALCULATED_DATE_OF_ONSET", "COUNTRY_OF_BIRTH", "YEAR_OF_ARRIVAL",
            "LGA", "ASSIGNED_TO",
        ]
    ]
    tab["Report_date"] = report_date
    tab.to_csv(f"cluster_report_{report_date}.csv", index=False)
    log.info(f"Written: cluster_report_{report_date}.csv")

    # -----------------------------------------------------------------------
    # 8. New-isolate summary table
    # -----------------------------------------------------------------------
    new_tab = tab[tab["Seq_ID"].isin(new_isos)]
    new_tab = new_tab[
        ["Seq_ID", "PHESS ID", "VIDRL Lab No.", "Phylogenetic lineage",
         "Cluster_poss", "Cluster_highly", "Cluster_ID"]
    ]
    new_tab = new_tab.rename(columns={"Seq_ID": "MDU ID", "Cluster_ID": "Cluster ID"})
    new_tab["MDU ID"] = numpy.where(new_tab["MDU ID"].isna(), new_tab["MDU ID"], new_tab["MDU ID"])
    new_tab["VIDRL Lab No."] = numpy.where(
        new_tab["VIDRL Lab No."].isna(), new_tab["VIDRL Lab No."], new_tab["VIDRL Lab No."]
    )
    new_tab["Cluster ID"] = numpy.where(
        new_tab["Cluster ID"].isna(), new_tab["Cluster ID"], new_tab["Cluster ID"]
    )
    new_tab = new_tab.drop_duplicates(subset=["MDU ID"])
    new_tab[["MDU ID", "PHESS ID", "VIDRL Lab No.", "Phylogenetic lineage", "Cluster ID"]].to_csv(
        "new_summary_table.csv", index=False
    )
    log.info("Written: new_summary_table.csv")

    # -----------------------------------------------------------------------
    # 9. Unclustered summary (new isolates only)
    # -----------------------------------------------------------------------
    un_cluster_df = tab[tab["Seq_ID"].isin(uncluster_list)]
    un_cluster_df = un_cluster_df[un_cluster_df["Seq_ID"].isin(new_isos)]
    un_cluster_df = un_cluster_df.rename(columns={"Seq_ID": "MDU ID", "Cluster_ID": "Cluster ID"})
    uncluster_table = un_cluster_df[
        [
            "MDU ID", "PHESS ID", "VIDRL Lab No.", "Surname 2x", "First Name 2x",
            "DOB", "Gender", "Collection date", "MANIFESTATION",
            "CALCULATED_DATE_OF_ONSET", "COUNTRY_OF_BIRTH", "YEAR_OF_ARRIVAL",
            "LGA", "ASSIGNED_TO",
        ]
    ]
    uncluster_table.to_csv("Uncluster_summary.csv", index=False)
    log.info("Written: Uncluster_summary.csv")

    # -----------------------------------------------------------------------
    # 10. Per-cluster outputs — only clusters containing >= 1 new isolate
    #     CSV includes ALL cluster members (new + historical) for full context
    # -----------------------------------------------------------------------
    for u in new_tab["Cluster_poss"].unique():
        if u == "UC":
            continue

        # Only process lineages that actually contain new isolates in this cluster
        ln = list(new_tab[new_tab["Cluster_poss"] == u]["Phylogenetic lineage"].dropna().unique())
        for l in ln:
            log.info(f"Processing cluster={u}  lineage={l}")
            sub_ln = f"Lineage_{l.split()[-1]}"

            # All isolates (new + historical) in THIS cluster within THIS lineage
            d = tab[(tab["Cluster_poss"] == u) & (tab["Phylogenetic lineage"] == l)]
            x = d.rename(columns={"Seq_ID": "MDU ID", "Cluster_ID": "Cluster ID"})
            seqs = list(x["MDU ID"].unique())
            log.debug(f"  All isolates in cluster: {seqs}")

            # --- Epi CSV (all cluster members, new + historical) ---
            for_table_epi = x[
                [
                    "MDU ID", "PHESS ID", "VIDRL Lab No.", "Surname 2x", "First Name 2x",
                    "DOB", "Gender", "Collection date", "Cluster ID", "MANIFESTATION",
                    "CALCULATED_DATE_OF_ONSET", "COUNTRY_OF_BIRTH", "YEAR_OF_ARRIVAL",
                    "LGA", "ASSIGNED_TO",
                ]
            ]
            epi_csv_path = f"{sub_ln}_{u}.csv"
            for_table_epi.to_csv(epi_csv_path, index=False)
            log.info(f"  Written: {epi_csv_path}")

            # --- SNP distance summary ---
            ds = pandas.read_csv(
                f"{analysis_path}/{sub_ln}/report/distances.tab", sep="\t"
            )
            new_seqs = [
                sk for sk in seqs
                if sk in inside_collection_day_list and sk != "2021-157374"
            ]
            log.debug(f"  New seqs for distance filtering: {new_seqs}")

            cols = ["Isolate"] + seqs
            cls_ds = ds[ds["Isolate"].isin(seqs)][cols]

            mlt_cls = pandas.melt(cls_ds, id_vars="Isolate", value_vars=seqs)
            mlt_cls = mlt_cls[mlt_cls["Isolate"] != mlt_cls["variable"]]
            mlt_cls["ids"] = mlt_cls[["Isolate", "variable"]].apply(
                lambda x: "_".join(sorted(list(set(x)))), axis=1
            )
            mlt_cls = mlt_cls.drop_duplicates(subset=["ids"])
            smm = mlt_cls.describe().T
            smm = smm.rename(
                columns={
                    "count": "Count",
                    "min": "Min distance",
                    "25%": "25th percentile",
                    "50%": "50th percentile (median)",
                    "75%": "75th percentile",
                    "max": "Max distance",
                }
            )
            smm["Count"] = len(seqs)
            bg_ds = pandas.melt(ds, id_vars="Isolate", value_vars=seqs)
            bg_ds = bg_ds[
                (bg_ds["Isolate"] != bg_ds["variable"])
                & (bg_ds["Isolate"] != "Reference")
                & (bg_ds["Isolate"] != "variable")
            ]
            bg_ds = bg_ds[~bg_ds["Isolate"].isin(seqs)]
            min_uc = bg_ds.describe().T["min"].values[0]
            med_uc = bg_ds.describe().T["50%"].values[0]
            smm["Distance to unclustered (min)"] = min_uc
            smm["Distance to unclustered (median)"] = med_uc
            smm = smm[
                [
                    "Count", "Min distance", "25th percentile",
                    "50th percentile (median)", "75th percentile", "Max distance",
                    "Distance to unclustered (min)", "Distance to unclustered (median)",
                ]
            ]
            dist_csv_path = f"{sub_ln}_{u}_dist_summary.csv"
            smm.to_csv(dist_csv_path, index=False)
            log.info(f"  Written: {dist_csv_path}")

            # --- Timeline chart (PNG) — only when cluster has > 2 isolates ---
            if len(seqs) > 2:
                log.info(f"  Drawing timeline chart for cluster={u} lineage={l} ({len(seqs)} isolates)")
                mltd = (
                    x.groupby(
                        [pandas.Grouper(key="Collection date", freq="1M"), "Cluster_highly"]
                    )
                    .agg("count")
                    .reset_index()
                )
                m = len(list(mltd["MDU ID"].unique()))

                chart = alt.Chart(mltd[mltd["Cluster_highly"] != "UC"]).mark_line().encode(
                    x=alt.X(
                        "yearmonth(Collection date)",
                        title="Collection date",
                        axis=alt.Axis(labelAngle=-90),
                    ),
                    y=alt.Y("Cluster_highly", title=""),
                    color=alt.Color(
                        "Cluster_highly", legend=alt.Legend(title="Highly related")
                    ),
                ).properties(width=700, height=300)

                chart += alt.Chart(mltd).mark_circle().encode(
                    x=alt.X(
                        "yearmonth(Collection date)",
                        title="Collection date",
                        axis=alt.Axis(labelAngle=-90),
                    ),
                    size=alt.Size(
                        "MDU ID:Q", legend=alt.Legend(title="Cases", tickCount=m)
                    ),
                    y=alt.Y("Cluster_highly", title=""),
                    color=alt.Color("Cluster_highly"),
                ).properties(width=700, height=300)

                # Output: Lineage_<lin>_<cluster>_his.png
                his_png = f"Lineage_{l.split()[-1]}_{u}_his.png"
                save_altair_chart(chart, his_png)

                # --- Annotation dict for tree tip colouring ---
                annotation_dict = {}
                for i in list(x["MDU ID"]):
                    annotation_dict[i] = {
                        "subcluster": x[x["MDU ID"] == i]["Cluster_highly"].values[0]
                    }

                # --- Phylogenetic tree ---
                node_id = dict(zip(x["MDU ID"], x["PHESS ID"]))
                log.debug(f"  node_id dict: {node_id}")

                tree = toytree.tree(f"{analysis_path}/{sub_ln}/report/core.newick")
                tree = tree.drop_tips(
                    [node for node in tree.get_tip_labels() if node not in seqs]
                )

                # Modify tip labels: append PHESS ID and assign subcluster colour
                for node in tree.treenode.traverse():
                    if node.is_leaf():
                        s = (
                            annotation_dict[node.name]["subcluster"]
                            if node.name in annotation_dict
                            else 428
                        )
                        phess_id = node_id.get(node.name, "NA")
                        new_name = f"{node.name} | {phess_id}"
                        node.name = new_name
                        node.add_feature("color", TIP_DICT.get(s, "#a4a9b3"))
                        node.add_feature("size", 10)
                    else:
                        node.add_feature("color", "black")
                        node.add_feature("size", 0)

                # Export filtered tree with modified tip labels
                l_safe = l.replace(" ", "_")
                filtered_tree_path = f"{u}_{l_safe}_core_filtered.newick"
                with open(filtered_tree_path, "w") as output_file:
                    output_file.write(tree.write())

                height = len(tree.get_tip_labels())
                colors = tree.get_node_values("color", show_root=1, show_tips=1)
                sizes = tree.get_node_values("size", show_root=1, show_tips=1)
                colorlist = [
                    TIP_DICT["new"] if tip.split(" | ")[0] in new_isos else "#black"
                    for tip in tree.get_tip_labels()
                ]
                tipnames = tree.get_tip_labels()

                canvas = toyplot.Canvas(width=600, height=height * 75)
                axes = canvas.cartesian()
                tree.draw(
                    axes=axes,
                    tip_labels=tipnames,
                    node_labels=False,
                    node_colors=colors,
                    node_sizes=sizes,
                    edge_colors="black",
                    edge_widths=2,
                    tip_labels_colors=colorlist,
                    tip_labels_style={"font-size": "16px"},
                )
                axes.show = False

                tree_svg = f"{u}_{l_safe}_tree.svg"
                tree_png = f"{u}_{l_safe}_tree.png"
                toyplot.svg.render(canvas, tree_svg)
                drawing = svg2rlg(tree_svg)
                renderPM.drawToFile(drawing, tree_png, fmt="PNG")
                log.info(f"  Written: {tree_png}")

    log.info("Done.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log.error(f"Fatal error: {exc}", exc_info=True)
        sys.exit(1)
