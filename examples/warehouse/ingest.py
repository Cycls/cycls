# A data warehouse on a volume: immutable Parquet partitions, one writer.
#
#   cycls volume create lake
#   cycls volume put lake ./events-2026-09-01.csv raw/2026-09-01.csv
#   uv run cycls run examples/warehouse/ingest.py::ingest --day 2026-09-01
#   uv run cycls deploy examples/warehouse/ingest.py
#
# A volume is shared files with no locking, so a DuckDB database file with two
# writers is not safe here. Write one Parquet file per partition instead, and
# let every reader open them read-only.
import datetime

import cycls

lake = cycls.Volume("lake")
image = cycls.Image().pip("duckdb")


@cycls.function(image=image, volumes={"/lake": lake}, memory="2Gi")
def ingest(day: str):
    """Convert one day of raw CSV into a Parquet partition."""
    import pathlib
    import re

    import duckdb

    # COPY ... TO takes a literal path, not a bound parameter, so the date is
    # validated before it reaches the SQL string.
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise ValueError(f"day must be YYYY-MM-DD, got {day!r}")

    raw = f"/lake/raw/{day}.csv"
    if not pathlib.Path(raw).exists():
        return {"day": day, "status": "missing"}

    pathlib.Path("/lake/events").mkdir(parents=True, exist_ok=True)
    out = f"/lake/events/{day}.parquet"

    con = duckdb.connect()
    con.execute(
        f"COPY (SELECT * FROM read_csv_auto('{raw}')) "
        f"TO '{out}' (FORMAT PARQUET, COMPRESSION ZSTD)"
    )
    rows = con.execute("SELECT count(*) FROM read_parquet(?)", [out]).fetchone()[0]
    return {"day": day, "rows": rows, "path": out}


@cycls.function(
    image=image,
    volumes={"/lake": lake},
    schedule=cycls.Cron("0 2 * * *", timezone="Asia/Riyadh"),
)
def nightly():
    """Scheduled runs take no arguments, so this one computes the day itself."""
    day = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    return ingest.remote(day)


@cycls.local_entrypoint
def backfill():
    # One file per day makes a rerun idempotent, which is what makes
    # at-least-once scheduling safe.
    days = [f"2026-09-{d:02d}" for d in range(1, 31)]
    for result in ingest.map(days):
        print(result)
