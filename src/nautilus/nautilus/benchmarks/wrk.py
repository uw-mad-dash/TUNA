import csv
import itertools
import logging
import operator
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from io import StringIO
from pathlib import Path
from string import Template
from subprocess import PIPE

import numpy as np
from nautilus.benchmarks import Benchmark, BenchmarkInfo, BenchmarkRound
from nautilus.config import NautilusConfig
from nautilus.dbms import DBMS
from nautilus.utils import disk_sync, run_command, trim_stream_output


@dataclass(frozen=True, eq=False)
class WrkWorkloadProperties:
    threadcount: int = 40
    clientcount: int = 40

    def __eq__(self, o):
        return self.threadcount == o.threadcount and self.clientcount == o.clientcount


@dataclass(frozen=True)
class WrkBenchmarkInfo(BenchmarkInfo):
    workload_properties: WrkWorkloadProperties = field(
        default_factory=WrkWorkloadProperties
    )


class Wrk(Benchmark):
    name = "wrk"
    workload_path: str = "/benchmark/wrk"

    dbms_binding: str

    def __init__(self, dbms: DBMS, info: WrkBenchmarkInfo) -> None:
        self.logger = logging.getLogger(self._logger_name)
        self.logger.info(f"wrk benchmark for DBMS: {dbms.name}")

        super().__init__(dbms, info)

        # Store info.workload_properties
        self.workload_properties = info.workload_properties

    def init(self):
        pass

    def load(self):
        """wrk does not require any loading as all arguments are loaded in the container"""
        load_info = {
            "stdout": "",
            "stderr": "",
        }
        return load_info

    def run(self, round: BenchmarkRound):
        """Execute the benchmark"""
        # Prepare command and run
        if round == BenchmarkRound.WARMUP:
            duration = self.info.warmup_duration
        else:
            duration = self.info.benchmark_duration
        cmd = f"wrk -t{self.workload_properties.threadcount} -c{self.workload_properties.clientcount} -d{duration} --timeout 1s -s /benchmark/wrk/wikipedia.lua http://{self.dbms.host}"
        self.logger.info(f"Starting {round.value} round...")

        start = datetime.now()
        cp = run_command(cmd, stdout=PIPE, stderr=PIPE, encoding="utf-8")
        end = datetime.now()

        self._handle_run_process_outcome(round, cp, start, end)
        return self._rounds_info[round.value]

    def _parse_perf_stats(self):
        perf_stats = {"name": "wkr"}

        parser = WrkParser()

        # Parse wrk metrics
        try:
            perf_stats["wrk"] = parser.parse_measurements(
                self.run_info["benchmark"]["stdout"]
            )
        except Exception as err:
            error_msg = repr(err)
            perf_stats["wrk_error_msg"] = error_msg
            self.logger.exception(f"While parsing wrk measurements: {error_msg}")
            if "wrk" not in perf_stats:
                perf_stats["wrk"] = None
        finally:
            perf_stats["wrk_result"] = "ok" if perf_stats["wrk"] else "error"

        del parser
        return perf_stats


class WrkParser:
    """wrk output/results parsing class"""

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)

        self.PERCENTILES = [
            50,
            90,
            95,
            99,
            99.999,
        ]
        self.PERCENTILES_STR = [f"{p}%" for p in self.PERCENTILES]

    def parse_measurements(self, stdout: str) -> dict:
        """
        Args:
            wrk_result_string: str. Text output from YCSB.

        Returns:
            A dictionary with keys:
            latency: dict mapping from percentile to latency in us.
            throughput: float. Throughput in tx/sec.
        Raises:
            IOError: If the results does not contain expected data.
        """
        result = {}
        result["latency"] = {}
        print(stdout)
        for p, ps in zip(self.PERCENTILES, self.PERCENTILES_STR):
            matches = re.findall(rf"\n{ps},([0-9\.]*)\s", stdout)
            if len(matches) == 1:
                if float(matches[0]) <= 0:
                    raise IOError("Error in wrk output: {}".format(stdout))
                result["latency"][p] = float(matches[0])
            else:
                raise IOError("Could not parse wrk output: {}".format(stdout))

        matches = re.findall(r"Requests\/sec:\s*([0-9\.]*)\s", stdout)
        if len(matches) == 1:
            result["throughput"] = float(matches[0])
        else:
            raise IOError("Could not parse wrk output: {}".format(stdout))

        return result
