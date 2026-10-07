import argparse
import pandas as pd
import shutil

def main():
    # Set up argument parsing
    parser = argparse.ArgumentParser(description='Check for duplicate entries in a CSV file.')
    parser.add_argument('filename', type=str, help='The CSV file to check for duplicates')
    parser.add_argument('--column', type=str, default='MDU ID', 
                       help='Column name to check for duplicates (default: "MDU ID")')
    args = parser.parse_args()

    # Read the CSV file
    df = pd.read_csv(args.filename)

    # Check for duplicates based on specified column
    duplicates = df[df.duplicated(subset=args.column, keep=False)]

    if not duplicates.empty:
        # Print duplicate entries found
        duplicate_counts = duplicates[args.column].value_counts()
        for value, count in duplicate_counts.items():
            print(f"Duplicate entries found for {args.column} {value}: {count} times")

        # Backup the original file
        backup_filename = args.filename.replace('.csv', '_original.csv')
        shutil.copyfile(args.filename, backup_filename)
        print(f"Original file backed up as {backup_filename}")

        # Remove duplicates and save the cleaned file
        df_cleaned = df.drop_duplicates(subset=args.column, keep='first')
        df_cleaned.to_csv(args.filename, index=False)
        print(f"Duplicate entries removed and saved to {args.filename}")
    else:
        print(f"No duplicate entries found for column '{args.column}'.")

if __name__ == "__main__":
    main()