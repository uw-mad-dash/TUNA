import argparse
import json
import logging
import multiprocessing.pool
import os
import pickle
import re
import shutil
import subprocess
import sys
import random
from datetime import datetime
import time
from concurrent import futures
from pathlib import Path
import jpype
import jpype.imports
jpype.startJVM(classpath = ['jars/*'])
import java

import grpc
import pandas as pd
import ray
import yaml
from benchmarks.Benchmark import (
    Benchmark,
    Canary,
    Fio,
    IntelMemoryLatencyChecker,
    PerfBenchSyscall,
    StressNGCache,
    StressNGCpu,
)
from executors.executor_v2 import NautilusExecutor
from proto import message_pb2, message_pb2_grpc


class EvaluatorServer(message_pb2_grpc.DistributedWorker):
    def __init__(self, dir: str):
        print(f"Working directory {dir}")

        self.benchmarks: dict[str, Benchmark] = {
            "bm_libaio_randwrite": Fio(
                type="randwrite", directory=dir, ioengine="libaio"
            ),
            "bm_libaio_randread": Fio(
                type="randread", directory=dir, ioengine="libaio"
            ),
            "bm_libaio_seqwrite": Fio(type="write", directory=dir, ioengine="libaio"),
            "bm_libaio_seqread": Fio(type="read", directory=dir, ioengine="libaio"),
            "bm_sync_randwrite": Fio(type="randwrite", directory=dir, ioengine="sync"),
            "bm_sync_randread": Fio(type="randread", directory=dir, ioengine="sync"),
            "bm_sync_seqwrite": Fio(type="write", directory=dir, ioengine="sync"),
            "bm_sync_seqread": Fio(type="read", directory=dir, ioengine="sync"),
            "bm_cache": StressNGCache(),
            "bm_cpu": StressNGCpu(),
            "bm_syscall": PerfBenchSyscall(),
            "bm_memory": IntelMemoryLatencyChecker(),
        }

        ray.init("ray://localhost:50050", runtime_env={"working_dir": "."})

    def _eval_config(
        self, request: message_pb2.Config, context: grpc.ServicerContext, stop=True
    ):
        self.executor = NautilusExecutor(host="localhost")

        if request.benchmarks:
            pre_results = {k: bm.run() for k, bm in self.benchmarks.items()}
        if request.metrics:
            canary = Canary()
            canary.start()

        print(request.dbms_info)
        perf = self.executor.evaluate_configuration(
            dbms_info=json.loads(request.dbms_info),
            benchmark_info=json.loads(request.benchmark_info),
            stop=stop,
        )
        if request.metrics:
            can_res = canary.stop()
        if request.benchmarks:
            post_results = {k: bm.run() for k, bm in self.benchmarks.items()}

        res_metrics = {}
        if request.metrics:
            res_metrics |= can_res
        if request.benchmarks:
            res_metrics |= {f"pre_{k}": v for k, v in pre_results.items()} | {
                f"post_{k}": v for k, v in post_results.items()
            }

        print(json.dumps(res_metrics))

        return message_pb2.Performanace(
            throughput=perf["throughput"],
            goodput=perf["goodput"],
            latencyp50=perf["latencyp50"],
            latencyp95=perf["latencyp95"],
            latencyp99=perf["latencyp99"],
            runtime=perf["runtime"],
            metrics=json.dumps(res_metrics),
        )

    def _eval_query(self, request: message_pb2.LossConfig, command: str, params: list):
        self.executor = NautilusExecutor(host="localhost")
        return self.executor.evaluate_query(
            dbms_info=json.loads(request.dbms_info), command=command, params=params
        )

    def _rpc_eval_config(
        self,
        request: message_pb2.Config,
        context: grpc.ServicerContext,
        stop: bool = True,
    ):
        print("received message")
        try:
            subprocess.run("sync", shell=True)
            subprocess.run('sudo sh -c "echo 1 > /proc/sys/vm/drop_caches"', shell=True)
            subprocess.run("sync", shell=True)
            subprocess.run('sudo sh -c "echo 2 > /proc/sys/vm/drop_caches"', shell=True)
            subprocess.run("sync", shell=True)
            subprocess.run('sudo sh -c "echo 3 > /proc/sys/vm/drop_caches"', shell=True)
            with multiprocessing.pool.ThreadPool() as pool:
                return_value = pool.apply_async(
                    self._eval_config, (request, context, stop)
                ).get(timeout=context.time_remaining())
        except multiprocessing.TimeoutError:
            # do something if timeout
            print("Timed Out")
            # restart nautilus
            subprocess.run("sudo docker kill dbms", shell=True)
            time.sleep(90)
            context.cancel()
        else:
            # do something with return_value
            return return_value

    def EvaluateConfig(
        self, request: message_pb2.Config, context: grpc.ServicerContext
    ):
        return self._rpc_eval_config(request, context)

    def CollectQueries(
        self, request: message_pb2.Config, context: grpc.ServicerContext
    ):
        try:
            os.remove(
                "/opt/nautilus/logs/postgresql.json",
            )
        except:
            pass

        self._rpc_eval_config(request, context, stop=False)
        Path("/opt/nautilus/logs/").mkdir(parents=True, exist_ok=True)
        with open("/opt/nautilus/logs/postgresql.json") as f:
            lines = f.readlines()

            data = [json.loads(line) for line in lines]
            data = [
                log
                for log in data
                if "ps" in log
                and log["ps"] != "SET"
                and log["ps"] != "BEGIN"
                and log["ps"] != "SHOW"
                and log["ps"] != "COMMIT"
                and log["ps"] != "ROLLBACK"
            ]

            sqls = [
                (
                    re.sub(r"^.*?:", "", line["message"]),
                    (
                        re.sub(r"^.*?:", "", line["detail"]).split(",")
                        if "detail" in line
                        else []
                    ),
                )
                for line in data
            ]

            df = pd.DataFrame(sqls, columns=["SQL", "parameters"])
            g = df.groupby(by=["SQL"])

            # reformat df
            tmp_df = g["parameters"].apply(list).reset_index()
            tmp_df["count"] = g["parameters"].count().reset_index()["parameters"]           
            

            with open(r"/opt/proxy/queries.pickle", "wb") as of:
                pickle.dump(tmp_df[tmp_df["count"] > 5], of)

        return message_pb2.Empty()

    def _plan_to_loss(self, plan: dict, multiplier: float = 1, func: message_pb2.LossFunction = message_pb2.LossFunction.LOSS_UNSPECIFIED) -> tuple[float, set[str], bool]:
        ratio: float = 100
        
        # Default to LOSS_L1
        if func == message_pb2.LossFunction.LOSS_UNSPECIFIED:
            func = message_pb2.LossFunction.LOSS_L1
        
        # Calc loss
        if func == message_pb2.LossFunction.LOSS_L1:
            loss = abs((ratio * plan["Actual Total Time"]) - plan["Total Cost"]) * multiplier
        elif func == message_pb2.LossFunction.LOSS_L2:
            loss = ((ratio * plan["Actual Total Time"]) - plan["Total Cost"]) ** 2 * multiplier
        elif func == message_pb2.LossFunction.LOSS_L1_Level:
            loss = abs((ratio * plan["Actual Total Time"]) - plan["Total Cost"]) * multiplier
            multiplier /= 2
        elif func == message_pb2.LossFunction.LOSS_L2_Level:
            loss = ((ratio * plan["Actual Total Time"]) - plan["Total Cost"]) ** 2 * multiplier
            multiplier /= 2
        
        operations = set([plan["Node Type"]])
        valid: bool = plan["Total Cost"] < 1000000
        
        if "Plans" in plan:
            for p in plan["Plans"]:
                sub_loss, sub_ops, sub_valid = self._plan_to_loss(p, multiplier)
                valid &= sub_valid
                operations |= sub_ops
                loss += sub_loss
        return loss, operations, valid 
            
    def _build_sql(self, sql: str, params: list[str]) -> str:
        # Turn prepared statements into parameratized statement
        num_params = sql.count('$')
        params = [re.findall(r"\s*\$[0-9]+\s*=\s*(.*)", param)[0] for param in params] 
        for idx in reversed(range(num_params)):
            sql = re.sub(rf"\${idx+1}+", params[idx], sql)     
        
            
        if "INSERT" in sql.upper():
            return f"EXPLAIN (ANALYZE, FORMAT JSON) {sql} ON CONFLICT DO NOTHING;"
        return f"EXPLAIN (ANALYZE, FORMAT JSON) {sql};"
    
    def _evaluate_sql(self, request: message_pb2.LossConfig, long_sql: str) -> tuple[float, bool]:
        # Turn prepared statements into parameratized statement
        
        results = self._eval_query(request, long_sql, None)
        
        plan_jsons = [json.loads(result.replace("\\n", "").replace("\\", ""))[0]["Plan"] for result in results ]
        loss_ops_valid = [self._plan_to_loss(plan_json) for plan_json in plan_jsons]
        
        return loss_ops_valid

    def _quick_set_config(self, request: message_pb2.LossConfig, context: grpc.ServicerContext):
        config: dict = json.loads(request.dbms_info)["config"]
        self._evaluate_sql(request, ';'.join([f"SET {k} TO {v}" for k, v in config.items()]) + ';')
            

    def EvaluateLoss(self, request: message_pb2.LossConfig, context: grpc.ServicerContext) -> message_pb2.Loss:
        self._quick_set_config(request, context)
        
        with open(r"/opt/proxy/queries.pickle", "rb") as f:
            df = pickle.load(f)
        
        total_queries = sum([len(p) for p in df["parameters"]])

        
        sql_weight = []
        for sql, p, count in zip(df["SQL"], df["parameters"], df["count"]):
            print("NUMBERS", count, total_queries, len(p))
            if len(p) == 0:
                sql_weight.append((self._build_sql(sql, []), count / total_queries))
            else:
                for rp in random.sample(p, 20):
                    sql_weight.append((self._build_sql(sql, rp), count / total_queries / 20))
        
        print(sql_weight)
        long_sql = "; ".join([s_w[0] for s_w in sql_weight])
        loss_ops_valid = self._evaluate_sql(request, long_sql)
        
        total_loss = sum([loss * weight * 100 if valid else 0 for (loss, ops, valid), (_, weight) in zip(loss_ops_valid, sql_weight)])
            
        print("TOTAL LOSS: ", total_loss)
            
        return message_pb2.Loss(loss=total_loss)

    def Ping(self, request, context):
        return message_pb2.Empty()


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=str, default="50051", required=False)
    parser.add_argument("--dir", type=str, default="./fio", required=False)
    args = parser.parse_args()
    return args.port, args.dir


def serve():
    port, dir = parse_args()

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=1))
    message_pb2_grpc.add_DistributedWorkerServicer_to_server(
        EvaluatorServer(dir), server
    )
    server.add_insecure_port("[::]:" + port)
    server.start()
    print("Server started, listening on " + port)
    server.wait_for_termination()


if __name__ == "__main__":
    logging.basicConfig()
    serve()
