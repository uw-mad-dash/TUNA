import dataclasses
import json

import ray

from nautilus.tasks import RunDBMSConfiguration
from nautilus.dbms import DBMSInfo
from nautilus.benchmarks.ycsb import YCSBBenchmarkInfo, YCSBWorkloadProperties
from nautilus.benchmarks.benchbase import BenchBaseInfo, BenchBaseWorkloadProperties

ray.init("ray://localhost:50050", runtime_env={"working_dir": "."})

dbms_info = dataclasses.asdict(DBMSInfo("redis", None, "7.2"))

## Test Benchbase
workload_properties = YCSBWorkloadProperties(
    recordcount=100_000, operationcount=100_000, threadcount=20
)
benchmark_info = dataclasses.asdict(
    YCSBBenchmarkInfo(
        "ycsb",
        "workloada",
        warmup_duration=10,
        benchmark_duration=30,
        workload_properties=workload_properties,
    )
)

actor = RunDBMSConfiguration.remote()

obj_ref = actor.run.remote(dbms_info, benchmark_info)
result = ray.get(obj_ref)

print("--------Output--------")
print(result)
print("--------Output--------")

ray.get(actor.cleanup.remote())
