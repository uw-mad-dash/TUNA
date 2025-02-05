import dataclasses
import json

import ray
from nautilus.benchmarks.benchbase import BenchBaseInfo, BenchBaseWorkloadProperties
from nautilus.benchmarks.ycsb import YCSBBenchmarkInfo, YCSBWorkloadProperties
from nautilus.dbms import DBMSInfo
from nautilus.tasks import RunDBMSConfiguration

ray.init()

dbms_info = dataclasses.asdict(
    DBMSInfo('postgres', None, '16.1'))

## Test Benchbase
workload_properties = BenchBaseWorkloadProperties(scalefactor=1, terminals=20)
benchmark_info = dataclasses.asdict(
    BenchBaseInfo('benchbase', 'tpcc', warmup_duration=10, benchmark_duration=10, workload_properties=workload_properties))

actor = RunDBMSConfiguration.remote()

samplers_info = {
    'postgres-sampler': {
        'class': 'DBMSMetricsSampler',
        'kwargs': {
            'interval': 5,
            'query_timeout_ms': 1000,
            'per_table_metrics': True,
        }
    }
}

obj_ref = actor.run.remote(dbms_info, benchmark_info, samplers_info=samplers_info)
result = ray.get(obj_ref)

with open('/nautilus/result.json', 'w') as f:
    json.dump(result, f, indent=2)

ray.get(actor.cleanup.remote())
