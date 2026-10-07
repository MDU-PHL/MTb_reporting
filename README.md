# MTB reporting pipeline

This repository contains the code for the MTB reporting pipeline. This repository serves to track the improvements made to the MTB reporting pipeline and to provide a reference for the code used in the pipeline.

```sh
ca MTB_reporting 
python3 scripts/qc.py 2026-09-28 tbtamr.csv --verbose

# do this for all Lineages (1-4)
for l in 1 2 3 4; do 
python3 scripts/cluster.py -d Lineage_${l}/report/distances.tab -t 5,12 -o Lineage_${l}/snp_clusters.txt.2026-09-28 --tab --zero-indexed -v
done

# MTB new process script
ca /home/khhor/conda/envs/cleptr_dev
python mtb_new_process.py --date 2026-09-28 --lineages 1,2,3,4 --analysis-path /home/mdu/analysis/surveillance/tb_dev --cleptr-db-path /home/mdu/analysis/surveillance/MTB_report/20260916_testing_scripts/cleptr_db --verbose

# merge cluster dbs
python merge_cluster_db.py --lineages 1,2,3,4 --cleptr-db-path /home/mdu/analysis/surveillance/MTB_report/20260916_testing_scripts/cleptr_db --output-name merged_cleptr_db.json --verbose --dry-run

# combine.py 
python3 combine.py --date 2026-09-28 --lineages 1,2,3,4 --cleptr-db-path /home/mdu/analysis/surveillance/MTB_report/20260916_testing_scripts/cleptr_db --verbose 2>&1 | tee -a combine.log.20260928

```

## Report preparation steps

```sh
ca /home/bisognor/.conda/envs/binf_tools
# ca /home/himals/conda/envs/MTB_reporting
# Update the master TBsharepoint.xlsx and tb_metadata.xlsx files using:
python3 update_sheets.py tb_isolates_metadata_20260914.xlsx -v

python3 ../../MTB_cleptr/MTB_new_report.py --date 2026-01-16

# Remove duplicates from the Lineage_1_610.csv file
python ../remove_duplicates.py Lineage_1_610.csv

# generate the MTB report document
python3 ../../MTB_cleptr/templete_fit.py --report R2026-017140


python3 ../../MTB_cleptr/modify_amr_table.py -r R2026-017140 

python ../prepare_cluster_table.py -r R2026-017140  -i new_summary_table.csv
```