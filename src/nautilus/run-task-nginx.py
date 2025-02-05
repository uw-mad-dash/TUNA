import dataclasses
import json

import ray
from nautilus.benchmarks.wrk import WrkBenchmarkInfo, WrkWorkloadProperties
from nautilus.dbms import DBMSInfo
from nautilus.tasks import RunDBMSConfiguration

ray.init()

dbms_info = dataclasses.asdict(DBMSInfo("nginx", None, "1.27"))

## Test Benchbase
workload_properties = WrkWorkloadProperties(threadcount=8, clientcount=40)
benchmark_info = dataclasses.asdict(
    WrkBenchmarkInfo(
        "wrk",
        "wrk",
        workload_properties=workload_properties,
        warmup_duration=30,
        benchmark_duration=300,
    )
)

actor = RunDBMSConfiguration.remote()

obj_ref = actor.run.remote(dbms_info, benchmark_info)
result = ray.get(obj_ref)

with open("/nautilus/result.json", "w") as f:
    json.dump(result, f, indent=2)

ray.get(actor.cleanup.remote())
