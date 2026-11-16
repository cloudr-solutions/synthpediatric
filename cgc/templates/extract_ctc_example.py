"""EXAMPLE ONLY: write the flat extract that `synthpediatric measure` reads.

WARNING: this is an illustration, not working CGC code. The table and column names in your
CGC workspace may differ from the ones used here (SOURCE_COLUMNS below). Check the real
names in your workspace first. This script does not call any CGC API: it assumes you have
already loaded the source table into a pandas DataFrame in your notebook, in whatever way
your workspace supports.

The measure tool needs one flat table with one row per participant, as CSV or parquet,
holding only the columns you will measure. Keep the file inside the CGC workspace. Only
the `measure_out/` folder it produces is exported.

Use it from a notebook like this (df is your loaded table):

    from extract_ctc_example import write_extract
    write_extract(df, "extract_ctc.csv")
"""
import pandas as pd

# EDIT: map the column names in your table (left) to the names used in the measure config
# (right). The right-hand names must match `frequencies`, `crosstabs` and `survival` in
# the config. If you prefer, leave the extract columns as they are and use `rename:` in
# the config instead.
SOURCE_COLUMNS = {
    "iccc_category": "iccc_category",
    "sex": "sex",
    "age_group": "age_group",
    "diagnosis_year_group": "diagnosis_year_group",
    "vital_status": "vital_status",
    "months": "months",   # follow-up time in months
    "event": "event",     # 1 = event (death), 0 = censored
}


def write_extract(df: pd.DataFrame, path: str = "extract_ctc.csv") -> pd.DataFrame:
    """Keep only the needed columns, one row per participant, and write a CSV or parquet file."""
    missing = [c for c in SOURCE_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"columns not found in the table: {missing}. Check SOURCE_COLUMNS.")
    out = df[list(SOURCE_COLUMNS)].rename(columns=SOURCE_COLUMNS)
    if out.index.duplicated().any():
        print("warning: duplicate index values; check that there is one row per participant")
    if path.endswith(".parquet"):
        out.to_parquet(path, index=False)
    else:
        out.to_csv(path, index=False)
    print(f"wrote {len(out)} rows to {path}")
    return out
