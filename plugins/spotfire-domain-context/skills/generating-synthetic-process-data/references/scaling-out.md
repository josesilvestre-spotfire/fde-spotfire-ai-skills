# Scaling out: billions of rows on Databricks or Snowflake

**Not yet tested** in this library. The patterns below come from porting one physics
simulator to Databricks and to Snowflake; the numbers are from that one build.

## Generate on executors, not the driver

Serial generation on the driver of about 2.4 billion rows ran at about 39,000 rows per
second, an estimate of 17 hours. Moving chunk generation onto the executors with
`mapInPandas` finished in about 13 minutes on 2 workers with 16 cores each and a 16-core
driver (about 80 times faster).

1. Build a small task table: one row per (plant, equipment, time chunk), with a seed derived
   deterministically from those keys.
2. `task_df.mapInPandas(generate_chunk, schema=explicit_schema)`, where `generate_chunk`
   yields one pandas frame per task row.
3. Write the result with `saveAsTable` to a Unity Catalog table, partitioned or clustered by
   time and asset.

Sketch (not run as written; `simulate`, `task_df` and `num_partitions` are yours):

```python
from pyspark.sql import types as T

schema = T.StructType([
    T.StructField("asset_id", T.StringType(), False),
    T.StructField("ts", T.TimestampType(), False),
    T.StructField("tag", T.StringType(), False),
    T.StructField("value", T.DoubleType(), True),
    T.StructField("event_id", T.StringType(), True),
])

def generate_chunk(batches):
    for tasks in batches:                       # an iterator of pandas frames
        for task in tasks.itertuples(index=False):
            frame = simulate(task.asset_id, task.start, task.end, seed=task.seed)
            yield frame.astype({"value": "float64"})

(task_df.repartition(num_partitions)            # Spark guidance: 2 to 4 per executor core
        .mapInPandas(generate_chunk, schema=schema)
        .write.mode("overwrite").saveAsTable("<catalog>.<schema>.<table>"))
```

## Determinism contract

The distributed path must produce exactly the values the sequential path produces.

1. Run the sequential path on a small slice and record value probes (random rows, checksums).
2. Run the distributed path on the same slice with the same seeds and assert the probes
   match. The reference port matched 6 of 6 probes.
3. Only then scale up. Seeds live in the task table, derived from the chunk keys, never from
   a global generator shared across chunks.

## Dtype discipline

- Pass an explicit Spark schema to every `createDataFrame` and `mapInPandas`; never infer.
- Enforce concrete pandas dtypes before the Spark boundary. A single object-dtype column (an
  event id column in the reference build) silently dropped PySpark off the Arrow fast path,
  which was the cause of the 17-hour estimate.
- Numeric missing values are `np.nan`; ids are proper string or integer types; avoid pandas
  nullable extension types at the boundary.

## Snowflake

- Write in chunks and keep a **resume ledger**: a table or file of committed chunk ids, so a
  crashed run resumes where it stopped and never regenerates a committed chunk.
- Set clustering keys for the downstream query pattern (time and asset).
- The same explicit-schema and concrete-dtype rules apply; most write-path failures in the
  reference port were dtype related.

## Execution and memory safety

- In interactive Windows or Jupyter sessions, `ProcessPoolExecutor` raised
  `BrokenProcessPool`; use `ThreadPoolExecutor` interactively and process pools only in batch
  scripts.
- Futures that keep their results alive cause `ArrowMemoryError` at scale. Use a bounded
  sliding window: keep at most N futures in flight, drain with `as_completed`, write, and drop
  each result immediately.

## Bookkeeping

Log continuously: target rows, rows per second, ETA, chunks committed against total. Finish
with a scale report: rows written, wall time, effective rows per second, events written. For
reference, one fleet build generated about 4 billion rows for 29 plants and 153 pieces of
equipment (about 17,000 events) in about 1.3 hours of generation.
