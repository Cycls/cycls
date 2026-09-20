# The read side of the warehouse: DuckDB over every Parquet partition.
#
#   uv run cycls run examples/warehouse/query.py --sql "SELECT count(*) FROM events"
#   uv run cycls deploy examples/warehouse/query.py
#
# After deploying, any machine with CYCLS_API_KEY can call it:
#   cycls.remote("query")("SELECT country, sum(amount) FROM events GROUP BY 1")
import cycls

lake = cycls.Volume("lake")


@cycls.function(
    image=cycls.Image().pip("duckdb"),
    volumes={"/lake": lake.read_only()},   # this deployment cannot modify the warehouse
    memory="4Gi",
)
def query(sql: str, limit: int = 200):
    import duckdb

    con = duckdb.connect()
    con.execute("CREATE VIEW events AS SELECT * FROM read_parquet('/lake/events/*.parquet')")
    con.execute("SET enable_external_access = false")   # no file or network reads from inside SQL

    rel = con.execute(f"SELECT * FROM ({sql}) LIMIT {int(limit)}")
    return {"columns": [d[0] for d in rel.description],
            "rows": [list(r) for r in rel.fetchall()]}
