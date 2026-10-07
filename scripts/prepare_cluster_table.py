#!/usr/bin/env python3
"""
Script to reformat TB cluster summary table with standardised headers.

This script reads a summary table CSV file and reformats it with specific
headers required for TB genomic reporting.
"""

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path


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


def read_input_csv(input_file):
    """
    Read the input CSV file.
    
    Args:
        input_file: Path to input CSV file
        
    Returns:
        List of dictionaries containing row data
    """
    log_message(f"Reading input file: {input_file}")
    data = []
    
    with open(input_file, 'r', encoding='utf-8') as f:
        # Read the csv file comma separated
        reader = csv.DictReader(f)
        for row in reader:
            data.append(row)
    
    log_message(f"Read {len(data)} rows from input file")
    return data


def reformat_data(input_data, report_id, report_date):
    """
    Reformat input data to output format.
    
    Args:
        input_data: List of dictionaries from input CSV
        report_id: Report ID string
        report_date: Report date in DD/MM/YYYY format
        
    Returns:
        List of dictionaries with reformatted data
    """
    log_message("Reformatting data...")
    output_data = []
    
    for row in input_data:
        output_row = {
            'PHESS ID': row.get('PHESS ID', '').strip(),
            'Lineage': row.get('Phylogenetic lineage', '').strip(),
            'Genomic report id': report_id,
            'Genomic cluster laboratory': 'MDU',
            'Genomic report date': report_date,
            'Genomic cluster': row.get('Cluster ID', '').strip(),
            'Genomic cluster threshold': '',
            'Secondary cluster': '',
            'Secondary cluster threshold': '',
            'MDU assigned cluster': row.get('Cluster ID', '').strip(),
            'Other reference': ''
        }
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
    
    fieldnames = [
        'PHESS ID',
        'Lineage',
        'Genomic report id',
        'Genomic cluster laboratory',
        'Genomic report date',
        'Genomic cluster',
        'Genomic cluster threshold',
        'Secondary cluster',
        'Secondary cluster threshold',
        'MDU assigned cluster',
        'Other reference'
    ]
    
    #  DEBUG: Print Genomic cluster and MDU assigned cluster values
    # for row in data:
    #     print(f"DEBUG: Genomic cluster: {row['Genomic cluster']}, MDU assigned cluster: {row['MDU assigned cluster']}")
    with open(output_file, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(data)
    
    log_message(f"Successfully wrote {len(data)} rows to output file")


def main():
    """Main function to orchestrate the reformatting process."""
    parser = argparse.ArgumentParser(
        description='Reformat TB cluster summary table with standardised headers.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage with auto-generated output filename and current date
  %(prog)s -i new_summary_table.csv -r RYYYY-XXXXXX
  
  # Specify custom output filename and date
  %(prog)s -i new_summary_table.csv -o output.csv -r RYYYY-XXXXXX -d 29/10/2025
  
  # Using long argument names
  %(prog)s --input new_summary_table.csv --report-id RYYYY-XXXXXX --date 29/10/2025

Input file format:
  The input CSV should have the following columns (comma separated):
    - MDU ID
    - PHESS ID
    - VIDRL Lab No.
    - Phylogenetic lineage
    - Cluster ID

Output file format:
  The output CSV will have following columns:
    - PHESS ID
    - Lineage
    - Genomic report id
    - Genomic cluster laboratory
    - Genomic report date
    - Genomic cluster
    - Genomic cluster threshold (empty)
    - Secondary cluster (empty)
    - Secondary cluster threshold (empty)
    - MDU assigned cluster
    - Other reference (empty)
        """
    )
    
    parser.add_argument(
        '-i', '--input',
        required=True,
        help='Input CSV file path (e.g., new_summary_table.csv)'
    )
    
    parser.add_argument(
        '-o', '--output',
        help='Output CSV file path (default: <report-id>-Cluster-table.csv)'
    )
    
    parser.add_argument(
        '-r', '--report-id',
        required=True,
        help='Report ID for the genomic report (e.g., RYYYY-XXXXXX)'
    )
    
    parser.add_argument(
        '-d', '--date',
        help='Report date in DD/MM/YYYY format (default: current date)'
    )
    
    args = parser.parse_args()
    
    try:
        log_message("Starting cluster table preparation")
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
            output_file = f"{args.report_id}-Cluster-table.csv"
        log_message(f"Output file: {output_file}")
        
        # Read input data
        input_data = read_input_csv(args.input)
        
        if not input_data:
            log_message("WARNING: No data rows found in input file")
            sys.exit(1)
        
        # Reformat data
        output_data = reformat_data(input_data, args.report_id, report_date)
        
        # Write output
        write_output_csv(output_file, output_data)
        
        log_message("Cluster table preparation completed successfully")
        
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