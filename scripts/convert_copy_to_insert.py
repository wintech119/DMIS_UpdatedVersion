#!/usr/bin/env python3
"""
Convert PostgreSQL pg_dump COPY ... FROM stdin; blocks into INSERT statements.

Usage: python scripts/convert_copy_to_insert.py \
    database_dump_2025-12-02.sql database_dump_corrections.sql

This script is conservative: it copies all lines from the input file to the
output, but when it finds a COPY ... FROM stdin; block it emits an equivalent
series of INSERT statements for each data row.

- Notes:
- Handles tab-separated COPY format where NULL is represented as \\N.
- Attempts to unescape common backslash escapes produced by pg_dump.
"""
import sys
import re


def unescape_copy_field(field: str) -> str:
    # Replace PostgreSQL COPY null marker
    if field == '\\N':
        return None

    # Unescape backslash escapes used in COPY text format
    # \\ -> \, \n -> newline, \t -> tab, \r -> carriage return
    s = field
    s = s.replace('\\\\', '\\')
    s = s.replace('\\n', '\n')
    s = s.replace('\\t', '\t')
    s = s.replace('\\r', '\r')

    # Now return Python string for SQL insertion (we'll quote later)
    return s


def quote_sql(value: str) -> str:
    if value is None:
        return 'NULL'
    # Escape single quotes for SQL
    v = value.replace("'", "''")
    return f"'{v}'"


def process_copy_block(outfile, first_line, infile_iter):
    # first_line contains: COPY schema.table (col1, col2, ...) FROM stdin;
    m = re.match(r"COPY\s+([\w\\\"]+)\.?(\"?\w+\"?)\s*\((.*)\)\s+FROM\s+stdin;", first_line, re.IGNORECASE)
    if not m:
        # Try simpler match for table with optional schema
        m2 = re.match(r"COPY\s+([\w\.\"]+)\s*\((.*)\)\s+FROM\s+stdin;", first_line, re.IGNORECASE)
        if not m2:
            # Fallback: write the original COPY block back
            outfile.write(first_line)
            for line in infile_iter:
                outfile.write(line)
                if line.strip() == "\\.":
                    break
            return
        full_table = m2.group(1)
        cols_raw = m2.group(2)
    else:
        schema = m.group(1)
        table = m.group(2)
        full_table = f"{schema}.{table}"
        cols_raw = m.group(3)

    cols = [c.strip() for c in cols_raw.split(',')]

    # Read data lines until a line with just \.
    rows = []
    for line in infile_iter:
        if line.strip() == "\\.":
            break
        # Remove trailing newline
        row_line = line.rstrip('\n')
        # Split by tabs
        fields = row_line.split('\t')
        values = []
        for f in fields:
            val = unescape_copy_field(f)
            values.append(val)
        rows.append(values)

    # Emit INSERT statements in a single transaction block for speed
    outfile.write(f"\n-- Converted COPY to INSERT for {full_table}\n")
    if not rows:
        outfile.write(f"-- (no rows)\n")
        return

    # Write INSERTs in batches to avoid extremely long statements
    batch_size = 500
    col_list = ', '.join(cols)
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i+batch_size]
        outfile.write(f"BEGIN;\n")
        for r in batch:
            # Ensure field count matches columns
            if len(r) != len(cols):
                # Pad with NULLs or truncate
                if len(r) < len(cols):
                    r = r + [None] * (len(cols) - len(r))
                else:
                    r = r[:len(cols)]

            vals_sql = ', '.join(quote_sql(v) for v in r)
            outfile.write(f"INSERT INTO {full_table} ({col_list}) VALUES ({vals_sql});\n")
        outfile.write("COMMIT;\n\n")


def convert_file(inpath: str, outpath: str):
    with open(inpath, 'r', encoding='utf-8', errors='replace') as infile, \
         open(outpath, 'w', encoding='utf-8') as outfile:

        it = iter(infile)
        for line in it:
            if line.lstrip().upper().startswith('COPY '):
                # Process the COPY block
                process_copy_block(outfile, line, it)
            else:
                outfile.write(line)


def main():
    if len(sys.argv) < 3:
        print("Usage: convert_copy_to_insert.py input.sql output.sql")
        sys.exit(2)
    inpath = sys.argv[1]
    outpath = sys.argv[2]
    print(f"Converting '{inpath}' -> '{outpath}' (this may take some time)...")
    convert_file(inpath, outpath)
    print("Done.")


if __name__ == '__main__':
    main()
