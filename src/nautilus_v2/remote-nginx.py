import dataclasses
import json

import ray

from nautilus.tasks import RunDBMSConfiguration
from nautilus.dbms import DBMSInfo
from nautilus.benchmarks.wrk import WrkBenchmarkInfo, WrkWorkloadProperties

ray.init("ray://localhost:50050", runtime_env={"working_dir": "."})

config = {"output_buffers": "8 128k"}
dbms_info = dataclasses.asdict(DBMSInfo("nginx", config, "1.27"))

## Test Benchbase
workload_properties = WrkWorkloadProperties(threadcount=40, clientcount=40)
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

print("--------Output--------")
print(result)
print("--------Output--------")

ray.get(actor.cleanup.remote())
