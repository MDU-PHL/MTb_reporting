#!/usr/bin/env python3
"""
Script to reformat TB AMR table with standardised headers.

This script reads a TB AMR CSV file and reformats it with specific
headers required for TB genomic reporting, extracting PHESS IDs from
a reference Excel file.
"""

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path
import pandas as pd


def log_message(message):
    """Print a timestamped log message."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] - {message}")


def validate_input_file(input_file):
    """
    Validate that the input file exists and is readable.
    
    Args:
        input_file: Path to the input CSV file
        
    Returns:
        Path object if valid
        
    Raises:
        FileNotFoundError if file doesn't exist
    """
    input_path = Path(input_file)
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_file}")
    if not input_path.is_file():
        raise ValueError(f"Input path is not a file: {input_file}")
    log_message(f"Input file validated: {input_file}")
    return input_path


def parse_date(date_string):
    """
    Parse and validate date string in DD/MM/YYYY format.
    
    Args:
        date_string: Date string to parse
        
    Returns:
        Formatted date string in DD/MM/YYYY format
        
    Raises:
        ValueError if date format is invalid
    """
    try:
        date_obj = datetime.strptime(date_string, "%d/%m/%Y")
        return date_obj.strftime("%d/%m/%Y")
    except ValueError:
        raise ValueError(f"Invalid date format: {date_string}. Expected DD/MM/YYYY")


def get_current_date():
    """
    Get current date in DD/MM/YYYY format.
    
    Returns:
        Current date string
    """
    return datetime.now().strftime("%d/%m/%Y")


def load_phess_mapping(excel_file):
    """
    Load PHESS ID mapping from Excel file.
    
    Args:
        excel_file: Path to TBsharepoint.xlsx file
        
    Returns:
        Dictionary mapping MDU ID to PHESS ID
    """
    log_message(f"Loading PHESS ID mapping from: {excel_file}")
    
    if not Path(excel_file).exists():
        log_message(f"WARNING: PHESS mapping file not found: {excel_file}")
        return {}
    
    try:
        df = pd.read_excel(excel_file)[["PHESS ID", "MDU ID"]]
        mapping = dict(zip(df["MDU ID"], df["PHESS ID"]))
        log_message(f"Loaded {len(mapping)} PHESS ID mappings")
        return mapping
    except Exception as e:
        log_message(f"WARNING: Could not load PHESS mapping: {e}")
        return {}

def get_phess_id(mdu_id, phess_mapping):
    """
    Extract PHESS ID for a given MDU sample ID.
    
    Args:
        mdu_id: MDU sample ID
        phess_mapping: Dictionary mapping MDU ID to PHESS ID
        
    Returns:
        PHESS ID string or empty string if not found
    """
    phess_id = phess_mapping.get(mdu_id, '')
    if not phess_id:
        log_message(f"WARNING: No PHESS ID found for MDU ID: {mdu_id}")
        return ''
    
    # Convert to int if it's a float to remove decimal point
    # Check for NaN before converting
    if isinstance(phess_id, float):
        if pd.isna(phess_id):
            log_message(f"WARNING: NaN PHESS ID for MDU ID: {mdu_id}")
            return ''
        phess_id = int(phess_id)
    
    return str(phess_id)

def read_input_csv(input_file):
    """
    Read the input AMR CSV file.
    
    Args:
        input_file: Path to input CSV file
        
    Returns:
        List of dictionaries containing row data
    """
    log_message(f"Reading input file: {input_file}")
    data = []
    
    with open(input_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            data.append(row)
    
    log_message(f"Read {len(data)} rows from input file")
    return data


def reformat_data(input_data, report_id, report_date, phess_mapping):
    """
    Reformat input AMR data to output format.
    
    Args:
        input_data: List of dictionaries from input CSV
        report_id: Report ID string
        report_date: Report date in DD/MM/YYYY format
        phess_mapping: Dictionary mapping MDU ID to PHESS ID
        
    Returns:
        List of dictionaries with reformatted data
    """
    log_message("Reformatting AMR data...")
    output_data = []
    
    # Define drug order as specified
    drugs = [
        'Rifampicin',
        'Isoniazid',
        'Pyrazinamide',
        'Ethambutol',
        'Moxifloxacin',
        'Amikacin',
        'Cycloserine',
        'Ethionamide',
        'Para-aminosalicylic acid',  # Will be output as "Paraa"
        'Clofazimine',
        'Delamanid',
        'Bedaquiline',
        'Linezolid',
        'Kanamycin',
        'Streptomycin',
        'Capreomycin'
    ]
    
    for row in input_data:
        mdu_id = row.get('MDU sample ID', '').strip()
        phess_id = get_phess_id(mdu_id, phess_mapping)
        
        output_row = {
            'PHESS_ID': phess_id,
            'Report_ID': report_id,
            'Report_Date': report_date,
            'Predicted_resistance': row.get('Predicted drug resistance', '').strip(),
            'Organism': row.get('Species', '').strip()
        }
        
        # Add drug interpretation and resistance genes
        for drug in drugs:
            interpretation_col = f"{drug} - Interpretation"
            resmech_col = f"{drug} - ResMech"
            
            # Use "Paraa" for Para-aminosalicylic acid in output
            drug_name = 'Paraa' if drug == 'Para-aminosalicylic acid' else drug
            
            output_row[drug_name] = row.get(interpretation_col, '').strip()
            output_row[f"{drug_name}_resistance_genes"] = row.get(resmech_col, '').strip()
        
        output_data.append(output_row)
    
    log_message(f"Reformatted {len(output_data)} rows")
    return output_data


def write_output_csv(output_file, data):
    """
    Write reformatted data to output CSV file.
    
    Args:
        output_file: Path to output CSV file
        data: List of dictionaries to write
    """
    log_message(f"Writing output file: {output_file}")
    
    # Define field order
    fieldnames = [
        'PHESS_ID',
        'Report_ID',
        'Report_Date',
        'Predicted_resistance',
        'Organism',
        'Rifampicin',
        'Rifampicin_resistance_genes',
        'Isoniazid',
        'Isoniazid_resistance_genes',
        'Pyrazinamide',
        'Pyrazinamide_resistance_genes',
        'Ethambutol',
        'Ethambutol_resistance_genes',
        'Moxifloxacin',
        'Moxifloxacin_resistance_genes',
        'Amikacin',
        'Amikacin_resistance_genes',
        'Cycloserine',
        'Cycloserine_resistance_genes',
        'Ethionamide',
        'Ethionamide_resistance_genes',
        'Paraa',
        'Paraa_resistance_genes',
        'Clofazimine',
        'Clofazimine_resistance_genes',
        'Delamanid',
        'Delamanid_resistance_genes',
        'Bedaquiline',
        'Bedaquiline_resistance_genes',
        'Linezolid',
        'Linezolid_resistance_genes',
        'Kanamycin',
        'Kanamycin_resistance_genes',
        'Streptomycin',
        'Streptomycin_resistance_genes',
        'Capreomycin',
        'Capreomycin_resistance_genes'
    ]
    
    with open(output_file, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(data)
    
    log_message(f"Successfully wrote {len(data)} rows to output file")


def main():
    """Main function to orchestrate the reformatting process."""
    parser = argparse.ArgumentParser(
        description='Reformat TB AMR table with standardised headers.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage with default input file and auto-generated output filename
  %(prog)s -r R2025-015032
  
  # Specify custom input and output files with date
  %(prog)s -i tbtamr.csv -o output.csv -r R2025-015032 -d 29/10/2025
  
  # Specify PHESS mapping file location
  %(prog)s -i tbtamr.csv -r R2025-015032 -p ../TBsharepoint.xlsx
  
  # Using long argument names
  %(prog)s --input tbtamr.csv --report-id R2025-015032 --date 29/10/2025

Input file format:
  The input CSV should be a comma-separated tbtamr.csv file with columns:
    - MDU sample ID
    - Item code
    - Species
    - Phylogenetic lineage
    - Predicted drug resistance
    - For each drug: <Drug> - ResMech, <Drug> - Interpretation, <Drug> - Confidence
    
  Supported drugs: Rifampicin, Isoniazid, Pyrazinamide, Ethambutol, Moxifloxacin,
                   Amikacin, Cycloserine, Ethionamide, Para-aminosalicylic acid,
                   Kanamycin, Streptomycin, Capreomycin, Clofazimine, Delamanid,
                   Bedaquiline, Linezolid

PHESS ID mapping:
  The script requires TBsharepoint.xlsx to map MDU IDs to PHESS IDs.
  By default, it looks for ../TBsharepoint.xlsx relative to the working directory.

Output file format:
  The output CSV will have columns:
    - PHESS_ID (extracted from TBsharepoint.xlsx)
    - Report_ID, Report_Date
    - Predicted_resistance, Organism
    - For each drug: <Drug>, <Drug>_resistance_genes
        """
    )
    
    parser.add_argument(
        '-i', '--input',
        default='tbtamr.csv',
        help='Input CSV file path (default: tbtamr.csv)'
    )
    
    parser.add_argument(
        '-o', '--output',
        help='Output CSV file path (default: <report-id>-AMR-table.csv)'
    )
    
    parser.add_argument(
        '-r', '--report-id',
        required=True,
        help='Report ID for the genomic report (e.g., R2025-015032)'
    )
    
    parser.add_argument(
        '-d', '--date',
        help='Report date in DD/MM/YYYY format (default: current date)'
    )
    
    parser.add_argument(
        '-p', '--phess-file',
        default='../TBsharepoint.xlsx',
        help='Path to TBsharepoint.xlsx for PHESS ID mapping (default: ../TBsharepoint.xlsx)'
    )
    
    args = parser.parse_args()
    
    try:
        log_message("Starting AMR table preparation")
        log_message(f"Report ID: {args.report_id}")
        
        # Validate input file
        input_path = validate_input_file(args.input)
        
        # Determine report date
        if args.date:
            report_date = parse_date(args.date)
            log_message(f"Using provided report date: {report_date}")
        else:
            report_date = get_current_date()
            log_message(f"Using current date: {report_date}")
        
        # Determine output file
        if args.output:
            output_file = args.output
        else:
            output_file = f"{args.report_id}-AMR-table.csv"
        log_message(f"Output file: {output_file}")
        
        # Load PHESS ID mapping
        phess_mapping = load_phess_mapping(args.phess_file)
        
        # Read input data
        input_data = read_input_csv(args.input)
        
        if not input_data:
            log_message("WARNING: No data rows found in input file")
            sys.exit(1)
        
        # Reformat data
        output_data = reformat_data(input_data, args.report_id, report_date, phess_mapping)
        
        # Write output
        write_output_csv(output_file, output_data)
        
        log_message("AMR table preparation completed successfully")
        
    except FileNotFoundError as e:
        log_message(f"ERROR: {e}")
        sys.exit(1)
    except ValueError as e:
        log_message(f"ERROR: {e}")
        sys.exit(1)
    except KeyError as e:
        log_message(f"ERROR: Missing required column in input file: {e}")
        sys.exit(1)
    except Exception as e:
        log_message(f"ERROR: Unexpected error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()