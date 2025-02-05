import dataclasses
import json
import logging
import os
import pathlib
import random
import subprocess
import sys
import time
from abc import ABC, abstractmethod
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import grpc
import numpy as np
import pandas as pd
import ray
from executors.grpc.nautilus_rpc_pb2 import EmptyMessage, ExecuteRequest
from executors.grpc.nautilus_rpc_pb2_grpc import ExecutionServiceStub
from google.protobuf.struct_pb2 import Struct

# pylint: disable=import-error
from nautilus.dbms.base import DBMSInfo
from nautilus.tasks import RunDBMSConfiguration


def run_command(cmd, **kwargs):
    logging.debug(f"Running command: `{cmd}`...")
    logging.debug(50 * "=")

    cp = None
    try:
        cp = subprocess.run(cmd, shell=True, **kwargs)
        if cp.returncode != 0:
            logging.warn(f"Non-zero code [{cp.returncode}] for command `{cmd}`")

    except Exception as err:
        logging.error(err)
        logging.error(f"Error while running command `{cmd}`")

    return cp


def trim_disks():
    logging.info("Executing TRIM on all mount points")
    try:
        run_command("sudo fstrim -av", check=True)
    except Exception as err:
        logging.warn(f"Error while TRIMing: {repr(err)}")
    logging.info("Completed TRIM on all mount points")


def get_measured_performance(perf_stats, benchmark):
    """Return throughput & 95-th latency percentile"""
    if benchmark == "ycsb":
        print(perf_stats)
        overall_stats = perf_stats["ycsb"]["groups"]["overall"]["statistics"]
        throughput, runtime = (
            overall_stats["Throughput(ops/sec)"],
            overall_stats["RunTime(ms)"] / 1000.0,
        )
        # Check if Return=ERROR in read/update results
        try:
            # Manually compute latency (weighted by ops)
            groups = [
                g
                for name, g in perf_stats["ycsb"]["groups"].items()
                if name != "overall"
            ]
            latency_info = [  # latencies are in micro-seconds
                (
                    float(g["statistics"]["50thPercentileLatency(ms)"]),
                    int(g["statistics"]["Operations"]),
                )
                for g in groups
            ]
            latencies, weights = tuple(zip(*latency_info))
            latencyp50 = np.average(latencies, weights=weights)

            latency_info = [  # latencies are in micro-seconds
                (
                    float(g["statistics"]["95thPercentileLatency(ms)"]),
                    int(g["statistics"]["Operations"]),
                )
                for g in groups
            ]
            latencies, weights = tuple(zip(*latency_info))
            latencyp95 = np.average(latencies, weights=weights)

            latency_info = [  # latencies are in micro-seconds
                (
                    float(g["statistics"]["99thPercentileLatency(ms)"]),
                    int(g["statistics"]["Operations"]),
                )
                for g in groups
            ]
            latencies, weights = tuple(zip(*latency_info))
            latencyp99 = np.average(latencies, weights=weights)
        except:
            logging.warning("Return=ERROR found in YCSB; Treating it as failed run!")
            throughput, latencyp50, latencyp95, latencyp99 = 0.1, 2**30, 2**30, 2**30
            error = True

    elif benchmark == "oltpbench":
        summary_stats = perf_stats["oltpbench_summary"]
        throughput, latency95, runtime = (
            summary_stats["throughput(req/sec)"],
            summary_stats["95th_lat(ms)"],
            summary_stats["time(sec)"],
        )
    elif benchmark == "benchbase":
        summary_stats = perf_stats["benchbase_summary"]
        throughput, goodput, latencyp99, latencyp95, latencyp50, runtime = (
            summary_stats["Throughput (requests/second)"],
            summary_stats["Goodput (requests/second)"],
            summary_stats["Latency Distribution"][
                "99th Percentile Latency (microseconds)"
            ],
            summary_stats["Latency Distribution"][
                "95th Percentile Latency (microseconds)"
            ],
            summary_stats["Latency Distribution"]["Median Latency (microseconds)"],
            float(summary_stats["Elapsed Time (nanoseconds)"]) / 10**9,
        )

        # hack for mysql
        return {
            "throughput": throughput,
            "goodput": goodput,
            "latencyp99": latencyp99,
            "latencyp95": latencyp95,
            "latencyp50": latencyp50,
            "runtime": runtime,
        }
    elif benchmark == "wrk":
        print(("=" * 50) + "PERF_STATS", perf_stats)
        throughput, latencyp99, latencyp95, latencyp50, runtime = (
            perf_stats["wrk"]["throughput"],
            perf_stats["wrk"]["latency"][99],
            perf_stats["wrk"]["latency"][95],
            perf_stats["wrk"]["latency"][50],
            -1,
        )
    else:
        raise NotImplementedError(f"Benchmark `{benchmark}` is not supported")

    return {
        "throughput": throughput,
        "goodput": throughput,
        "latencyp99": latencyp99,
        "latencyp95": latencyp95,
        "latencyp50": latencyp50,
        "runtime": runtime,
    }


def get_dbms_metrics(results, num_expected):
    """Parses DBMS metrics and returns their mean as a numpy array

    NOTE: Currently only DB-wide metrics are parsed; not table-wide ones
    """
    GLOBAL_STAT_VIEWS = ["pg_stat_bgwriter", "pg_stat_database"]
    PER_TABLE_STAT_VIEWS = [  # Not used currently
        "pg_stat_user_tables",
        "pg_stat_user_indexes",
        "pg_statio_user_tables",
        "pg_statio_user_indexes",
    ]
    try:
        metrics = json.loads(results["samplers"]["db_metrics"])["postgres"]
        samples = metrics["samples"]
    except Exception as err:
        logging.error(f"Error while *retrieving* DBMS metrics: {repr(err)}")
        logging.info("Returning dummy (i.e., all zeros) metrics")
        return np.zeros(num_expected)

    try:
        global_dfs = []
        for k in GLOBAL_STAT_VIEWS:
            s = samples[k]
            v = [l for l in s if l != None]
            cols = [f"{k}_{idx}" for idx in range(len(v[0]))]

            df = pd.DataFrame(data=v, columns=cols)
            df.dropna(axis=1, inplace=True)
            df = df.select_dtypes(["number"])
            global_dfs.append(df)

        df = pd.concat(global_dfs, axis=1)
        metrics = df.mean(axis=0).to_numpy()
    except Exception as err:
        logging.error(f"Error while *parsing* DBMS metrics: {repr(err)}")
        logging.info("Returning dummy (i.e., all zeros) metrics")
        return np.zeros(num_expected)

    if len(metrics) != num_expected:
        logging.error(
            f"Num of metrics [{len(metrics)}] is different than expected [{num_expected}] :("
        )
        logging.info("Returning dummy (i.e., all zeros) metrics")
        return np.zeros(num_expected)

    return metrics


def is_result_valid(results, benchmark):
    # Check results
    run_info, perf_stats = results["run_info"], results["performance_stats"]

    if benchmark == "ycsb":
        check_fields = [
            run_info["warmup"]["result"],
            run_info["benchmark"]["result"],
            perf_stats["ycsb_result"],
        ]
    elif benchmark == "oltpbench":
        check_fields = [
            run_info["benchmark"]["result"],
            perf_stats["oltpbench_summary_result"],
        ]
    elif benchmark == "benchbase":
        check_fields = [
            run_info["benchmark"]["result"],
            perf_stats["benchbase_summary_result"],
        ]
    elif benchmark == "wrk":
        check_fields = [perf_stats["wrk_result"]]
    else:
        raise NotImplementedError(f"Benchmark `{benchmark}` is not supported")

    return all(v == "ok" for v in check_fields)


class ExecutorInterface(ABC):
    def __init__(self, **kwargs):
        None

    @abstractmethod
    def evaluate_configuration(self, dbms_info, benchmark_info, stop=True):
        raise NotImplementedError


class DummyExecutor(ExecutorInterface):
    def __init__(self, parse_metrics=False, num_dbms_metrics=None, **kwargs):
        self.parse_metrics = parse_metrics
        self.num_dbms_metrics = num_dbms_metrics

    def evaluate_configuration(self, dbms_info, benchmark_info, stop=True):
        perf = {
            "throughput": float(random.randint(1000, 10000)),
            "goodput": float(random.randint(1000, 10000)),
            "latency": float(random.randint(1000, 10000)),
            "runtime": 0,
        }

        if not self.parse_metrics:
            return perf

        metrics = np.random.rand(self.num_dbms_metrics)
        return perf, metrics


class NautilusExecutor(ExecutorInterface):
    GRPC_MAX_MESSAGE_LENGTH = 32 * (2**20)  # 32MB
    # NOTE: Nautilus already has a soft time limit (default is *1.5 hour*)
    EXECUTE_TIMEOUT_SECS = 2 * 60 * 60  # 4 hours

    def __init__(
        self,
        host=None,
        n_retries=10,
        parse_metrics=False,
        num_dbms_metrics=None,
    ):
        self.host = host
        self.iter = 0
        self.parse_metrics = parse_metrics
        if parse_metrics:
            assert num_dbms_metrics >= 0
            self.num_dbms_metrics = num_dbms_metrics

    def evaluate_configuration(self, dbms_info, benchmark_info, stop=True):
        """Call Nautilus executor RPC"""

        # NOTE: protobuf explicitely converts ints to floats; this is a workaround
        # https://stackoverflow.com/questions/51818125/how-to-use-ints-in-a-protobuf-struct
        config = {}
        for k, v in dbms_info["config"].items():
            if isinstance(v, int):
                config[k] = str(v)
            else:
                config[k] = v

        # Construct request
        dbms_info = dataclasses.asdict(
            DBMSInfo(dbms_info["name"], dbms_info["config"], dbms_info["version"])
        )

        # Do RPC
        actor = RunDBMSConfiguration.remote()
        obj_ref = actor.run.remote(dbms_info, benchmark_info, _stop=stop)
        results = ray.get(obj_ref)
        ray.get(actor.cleanup.remote())

        self.iter += 1
        # Check results
        try:
            is_valid = is_result_valid(results, benchmark_info["name"])
        except Exception as err:
            logging.error(f"Exception while trying to check result: {str(err)}")
            is_valid = False
        finally:
            if not is_valid:
                logging.error("Nautilus experienced an error.. check logs :(")
                return (
                    None
                    if not self.parse_metrics
                    else (None, np.zeros(self.num_dbms_metrics))
                )

        # Retrieve throughput & latency stats
        print(results)
        perf = get_measured_performance(
            results["performance_stats"], benchmark_info["name"]
        )

        logging.info("Results: ", perf)

        if not self.parse_metrics:
            return perf

        # Parse DBMS metrics and return along with perf
        return perf, get_dbms_metrics(results, self.num_dbms_metrics)

    def evaluate_query(self, dbms_info, command, params):
        """Call Nautilus executor RPC"""

        config = {}
        for k, v in dbms_info["config"].items():
            if isinstance(v, int):
                config[k] = str(v)
            else:
                config[k] = v

        # Construct request
        dbms_info = dataclasses.asdict(
            DBMSInfo(dbms_info["name"], dbms_info["config"], dbms_info["version"])
        )

        # Do RPC
        actor = RunDBMSConfiguration.remote()
        obj_ref = actor.run_command.remote(dbms_info, command, params)
        results = ray.get(obj_ref)
        # ray.get(actor.cleanup.remote()

        return results

    def close(self):
        """Close connection to Nautilus"""
        self.channel.close()

    def _try_connect(self, **kwargs):
        """Attempt to connect to host:port address"""
        self.channel = grpc.insecure_channel(
            f"{self.host}:{self.port}",
            options=[  # send/recv up to 32 MB of messages (4MB default)
                ("grpc.max_send_message_length", self.GRPC_MAX_MESSAGE_LENGTH),
                ("grpc.max_receive_message_length", self.GRPC_MAX_MESSAGE_LENGTH),
            ],
        )
        self.stub = ExecutionServiceStub(self.channel)

        response = self.stub.Heartbeat(EmptyMessage(), **kwargs)
        logging.info(f'{10*"="} Nautilus Info {10*"="}')
        logging.info(f"Alive since  : {response.alive_since.ToDatetime()}")
        logging.info(f"Current time : {response.time_now.ToDatetime()}")
        logging.info(f"Jobs finished: {response.jobs_finished}")
        logging.info(f'{35 * "="}')


class ExecutorFactory:
    concrete_classes = {
        "NautilusExecutor": NautilusExecutor,
        "DummyExecutor": DummyExecutor,
    }

    @staticmethod
    def from_config(config, **extra_kwargs):
        executor_config = deepcopy(config["executor"])

        classname = executor_config.pop("classname", None)
        assert classname != None, "Please specify the *executor* class name"

        try:
            class_ = ExecutorFactory.concrete_classes[classname]
        except KeyError:
            raise ValueError(
                f'Executor class "{classname}" not found. '
                f'Options are [{", ".join(ExecutorFactory.concrete_classes.keys())}]'
            )

        # Override with local
        executor_config.update(**extra_kwargs)

        return class_(**executor_config)
