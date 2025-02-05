import argparse
import json
import logging
import sys
from threading import Thread
from typing import Optional

import client.utils
import ConfigSpace as CS
import numpy as np
import pandas as pd
from client.reproducible import fix_global_random_state
from evaluation_client import Evaluator
from proto import message_pb2


def evaluate(
    clnt: Evaluator,
    config: dict,
    result: list[Optional[float]],
    index: int,
    target: str,
) -> None:
    retry = 0

    while retry < 3:
        retry += 1
        try:
            res: message_pb2.Performanace = clnt.evaluate(config)

            if res is None:
                continue

            if target == "throughput":
                result[index] = res.throughput
            elif target == "runtime":
                result[index] = res.runtime
            elif target == "latencyp50":
                result[index] = res.latencyp50
            elif target == "latencyp95":
                result[index] = res.latencyp95
            elif target == "latencyp99":
                result[index] = res.latencyp99

            if result[index] == None or result[index] == 0:
                continue

            return
        except Exception as e:
            print(e)


def main() -> int:
    with open("spaces/benchmark/tpcc.json") as f:
        tpcc_bm = json.load(f)
    with open("spaces/benchmark/epinions.json") as f:
        epinions_bm = json.load(f)
    with open("spaces/benchmark/tpch.json") as f:
        tpch_bm = json.load(f)
    with open("spaces/benchmark/ycsb.json") as f:
        ycsb_bm = json.load(f)
    with open("spaces/benchmark/ycsbc-redis.json") as f:
        ycsbc_redis_bm = json.load(f)
    with open("spaces/benchmark/sample_mssales.json") as f:
        mssales_bm = json.load(f)
    with open("spaces/benchmark/wrk.json") as f:
        wrk_bm = json.load(f)
    with open("spaces/dbms/postgres-16.1.json") as f:
        pg_dbms = json.load(f)
    with open("spaces/dbms/mysql-8.3.json") as f:
        my_dbms = json.load(f)
    with open("spaces/dbms/redis-7.2.json") as f:
        redis_dbms = json.load(f)
    with open("spaces/dbms/nginx-1.27.json") as f:
        nginx_dbms = json.load(f)

    logging.root.setLevel(logging.NOTSET)
    fix_global_random_state(seed=1)

    hosts = client.utils.load_hosts("hosts.azure")
    df = pd.read_pickle("best.pickle")

    results = []
    for index, row in df.reset_index().iterrows():
        print("Starting ", index)

        if "cluster_cl" in row["Source"]:
            bm = tpcc_bm
            target = "throughput"
            dbms = pg_dbms
        elif "cluster3_mssales" in row["Source"]:
            bm = mssales_bm
            target = "runtime"
            dbms = pg_dbms
        elif "cluster4_ablation_outlier" in row["Source"]:
            bm = tpcc_bm
            target = "throughput"
            dbms = pg_dbms
        elif "cluster2_mysql" in row["Source"]:
            bm = tpcc_bm
            target = "throughput"
            dbms = my_dbms
        elif "cluster1_tpch" in row["Source"]:
            bm = tpch_bm
            target = "runtime"
            dbms = pg_dbms
        elif "tpcc" in row["Source"]:
            bm = tpcc_bm
            target = "throughput"
            dbms = pg_dbms
        elif "epinions" in row["Source"]:
            bm = epinions_bm
            target = "throughput"
            dbms = pg_dbms
        elif "tpch" in row["Source"]:
            bm = tpch_bm
            target = "latency50"
            dbms = pg_dbms
        elif "cluster1" in row["Source"]:
            bm = tpcc_bm
            target = "throughput"
            dbms = pg_dbms
        elif "cluster2" in row["Source"]:
            bm = epinions_bm
            target = "throughput"
            dbms = pg_dbms
        elif "cluster3" in row["Source"]:
            bm = tpch_bm
            target = "latency50"
            dbms = pg_dbms
        elif "redisycsbc" in row["Source"]:
            bm = ycsbc_redis_bm
            target = "latencyp95"
            dbms = redis_dbms
        elif "redis" in row["Source"]:
            bm = ycsb_bm
            target = "latencyp95"
            dbms = redis_dbms
        elif "nginx" in row["Source"]:
            bm = wrk_bm
            target = "latencyp95"
            dbms = nginx_dbms

        res: list[Optional[float]] = [None] * len(hosts)
        threads: list[Thread] = [
            Thread(
                target=evaluate,
                args=(
                    client.utils.host_to_evaluator(host, dbms, bm),
                    row["CleanConfig"],
                    res,
                    index,
                    target,
                ),
            )
            for index, host in enumerate(hosts)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        res.append(row["CleanConfig"])
        res.append(row["Source"])
        results.append(res)
    res_df = pd.DataFrame(np.row_stack(results))
    res_df.to_pickle("rerun.pickle")


if __name__ == "__main__":
    sys.exit(main())
