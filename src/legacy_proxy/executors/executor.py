import json
import logging
import os
import pathlib
import random
import subprocess
import time
from abc import ABC, abstractmethod
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import grpc
import numpy as np
import pandas as pd

# pylint: disable=import-error
from executors.grpc.nautilus_rpc_pb2 import EmptyMessage, ExecuteRequest
from executors.grpc.nautilus_rpc_pb2_grpc import ExecutionServiceStub
from google.protobuf.json_format import MessageToDict
from google.protobuf.struct_pb2 import Struct
from scipy.spatial.distance import cityblock, euclidean
from sklearn.preprocessing import StandardScaler


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
        overall_stats = perf_stats["ycsb"]["groups"]["overall"]["statistics"]
        throughput, runtime = (
            overall_stats["Throughput(ops/sec)"],
            overall_stats["RunTime(ms)"] / 1000.0,
        )

        # Check if Return=ERROR in read/update results
        error = False
        try:
            read_stats = perf_stats["ycsb"]["groups"]["read"]["statistics"]
            assert "Return=ERROR" not in read_stats.keys()
            update_stats = perf_stats["ycsb"]["groups"]["update"]["statistics"]
            assert "Return=ERROR" not in update_stats.keys()
        except AssertionError:
            logging.warning("Return=ERROR found in YCSB; Treating it as failed run!")
            throughput, latencyp50, latencyp95, latencyp99 = 0.1, 2**30, 2**30, 2**30
            error = True

        if not error:
            # Manually compute latency (weighted by ops)
            groups = [
                g
                for name, g in perf_stats["ycsb"]["groups"].items()
                if name != "overall"
            ]
            latency_info = [  # latencies are in micro-seconds
                (float(g["statistics"]["p50"]), int(g["statistics"]["Return=OK"]))
                for g in groups
            ]
            latencies, weights = tuple(zip(*latency_info))
            latencyp50 = np.average(latencies, weights=weights) / 1000.0

            latency_info = [  # latencies are in micro-seconds
                (float(g["statistics"]["p95"]), int(g["statistics"]["Return=OK"]))
                for g in groups
            ]
            latencies, weights = tuple(zip(*latency_info))
            latencyp95 = np.average(latencies, weights=weights) / 1000.0

            latency_info = [  # latencies are in micro-seconds
                (float(g["statistics"]["p99"]), int(g["statistics"]["Return=OK"]))
                for g in groups
            ]
            latencies, weights = tuple(zip(*latency_info))
            latencyp99 = np.average(latencies, weights=weights) / 1000.0

    elif benchmark == "oltpbench":
        summary_stats = perf_stats["oltpbench_summary"]
        throughput, latency, runtime = (
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
            perf_stats["benchbase_samples"]["Time (seconds)"][-1],
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
            run_info["warm_up"]["result"],
            run_info["benchmark"]["result"],
            perf_stats["ycsb_result"],
            perf_stats["ycsb_raw_result"],
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
    else:
        raise NotImplementedError(f"Benchmark `{benchmark}` is not supported")

    return all(v == "ok" for v in check_fields)


class ExecutorInterface(ABC):
    def __init__(self, **kwargs):
        None

    @abstractmethod
    def evaluate_configuration(self, dbms_info, benchmark_info):
        raise NotImplementedError


class DummyExecutor(ExecutorInterface):
    def __init__(self, parse_metrics=False, num_dbms_metrics=None, **kwargs):
        self.parse_metrics = parse_metrics
        self.num_dbms_metrics = num_dbms_metrics

    def evaluate_configuration(self, dbms_info, benchmark_info):
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
        port=None,
        n_retries=10,
        parse_metrics=False,
        num_dbms_metrics=None,
    ):
        self.host, self.port = host, port
        self.iter = 0
        self.parse_metrics = parse_metrics
        if parse_metrics:
            assert num_dbms_metrics >= 0
            self.num_dbms_metrics = num_dbms_metrics

        delay = 2
        for idx in range(1, n_retries + 1):
            logging.debug(f"Trying connecting to Nautilus [#={idx}]...")
            try:
                self._try_connect(timeout=5)
            except Exception as err:
                logging.debug(f"Failed to connect: {repr(err)}")
                logging.debug(f"Trying again in {delay} seconds")
                time.sleep(delay)
                delay *= 2
            else:
                logging.info("Connected to Nautilus!")
                return

        raise RuntimeError(f"Cannot connect to Nautilus @ {host}:{port}")

    def evaluate_configuration(self, dbms_info, benchmark_info):
        """Call Nautilus executor RPC"""
        # trim disks before sending request
        # trim_disks()

        # NOTE: protobuf explicitely converts ints to floats; this is a workaround
        # https://stackoverflow.com/questions/51818125/how-to-use-ints-in-a-protobuf-struct
        config = {}
        for k, v in dbms_info["config"].items():
            if isinstance(v, int):
                config[k] = str(v)
            else:
                config[k] = v
        dbms_info["config"] = config

        # Construct request
        config = Struct()
        config.update(dbms_info["config"])  # pylint: disable=no-member
        dbms_info = ExecuteRequest.DBMSInfo(
            name=dbms_info["name"], config=config, version=dbms_info["version"]
        )

        if benchmark_info["name"] == "ycsb":
            request = ExecuteRequest(dbms_info=dbms_info, ycsb_info=benchmark_info)
        elif benchmark_info["name"] == "oltpbench":
            request = ExecuteRequest(dbms_info=dbms_info, oltpbench_info=benchmark_info)
        elif benchmark_info["name"] == "benchbase":
            request = ExecuteRequest(dbms_info=dbms_info, benchbase_info=benchmark_info)
        else:
            raise ValueError(f"Benchmark `{benchmark_info['name']}' not found")

        # Do RPC
        logging.info(f"Calling Nautilus RPC")
        print(f"with request:\n{request}")
        try:
            response = self.stub.Execute(request, timeout=self.EXECUTE_TIMEOUT_SECS)
        except Exception as err:
            logging.error(f"Error while submitting task: {repr(err)}")
            with open("error.txt", "a") as f:
                f.write(repr(err))

        logging.info(f"Received response JSON [len={len(response.results)}]")
        resp_dict = MessageToDict(response)

        pathlib.Path("/opt/logs").mkdir(parents=True, exist_ok=True)
        with open(
            f"/opt/logs/benchbase_{datetime.now().strftime('%Y%m%d%H%M%S')}.json", "w"
        ) as f:
            json.dump(resp_dict, f, indent=3)

        results = resp_dict["results"]

        self.iter += 1
        # Check results
        try:
            print(results)
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
        print(results["performance_stats"])
        perf = get_measured_performance(
            results["performance_stats"], benchmark_info["name"]
        )

        logging.info("Results: ", perf)

        if not self.parse_metrics:
            return perf

        # Parse DBMS metrics and return along with perf
        return perf, get_dbms_metrics(results, self.num_dbms_metrics)

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
