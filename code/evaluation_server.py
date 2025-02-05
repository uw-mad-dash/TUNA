import argparse
import json
import logging
import multiprocessing.pool
import os
import shutil
import subprocess
import sys
import time
from concurrent import futures

import grpc
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
from executors.executor import NautilusExecutor
from proto import message_pb2, message_pb2_grpc


class EvaluatorServer(message_pb2_grpc.DistributedWorker):
    def __init__(self, dir: str):
        with open("/opt/nautilus/nautilus/config.yaml", "r") as file:
            self.env = yaml.safe_load(file)["env"]
        print("env", self.env)

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

    def _eval_config(self, request: message_pb2.Config, context: grpc.ServicerContext):
        self.executor = NautilusExecutor(host="localhost", port="1337")

        if request.benchmarks:
            pre_results = {k: bm.run() for k, bm in self.benchmarks.items()}
        if request.metrics:
            canary = Canary()
            canary.start()
        perf = self.executor.evaluate_configuration(
            dbms_info=json.loads(request.dbms_info),
            benchmark_info=json.loads(request.benchmark_info),
        )
        if request.metrics:
            can_res = canary.stop()
        if request.benchmarks:
            post_results = {k: bm.run() for k, bm in self.benchmarks.items()}

        id: int = len(next(os.walk("/opt/output"))[1])
        try:
            shutil.copytree(
                "/mnt/ssd/postgres/data/pg_log", f"/opt/output/{id}", dirs_exist_ok=True
            )
        except Exception as e:
            print(e)

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

    def EvaluateConfig(
        self, request: message_pb2.Config, context: grpc.ServicerContext
    ):
        try:
            subprocess.run("sync", shell=True)
            subprocess.run('sudo sh -c "echo 1 > /proc/sys/vm/drop_caches"', shell=True)
            subprocess.run("sync", shell=True)
            subprocess.run('sudo sh -c "echo 2 > /proc/sys/vm/drop_caches"', shell=True)
            subprocess.run("sync", shell=True)
            subprocess.run('sudo sh -c "echo 3 > /proc/sys/vm/drop_caches"', shell=True)
            with multiprocessing.pool.ThreadPool() as pool:
                return_value = pool.apply_async(
                    self._eval_config, (request, context)
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
