import datetime
import glob
import logging
import os
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path

import benchmarks.utils
import numpy as np
import pandas as pd
import psutil
import regex as re


# Requires Definition of _verify_command
class CommandWrapper(ABC):
    def __init__(self):
        self._verify_installation()

    def _verify_installation(self) -> bool:
        try:
            benchmarks.utils.run_command_simple(self._verify_command)
            return True
        except Exception as e:
            print(e)
            pass
        return self._repair_instalation()

    def _repair_instalation(self) -> bool:
        benchmarks.utils.run_command_simple(["sudo", "apt", "update"])
        benchmarks.utils.run_command_simple(self._install_command)


# Requires Definition of _run_command
class Benchmark(CommandWrapper):
    def run(self) -> float:
        try:
            return self._extract(benchmarks.utils.run_command_simple(self._run_command))
        except Exception as e:
            print(e)
            return -1

    @abstractmethod
    def _extract(self, results) -> float:
        pass


class IntelMemoryLatencyChecker(Benchmark):
    def __init__(self):
        self._verify_command = ["/opt/mlc/Linux/mlc", "-X", "--bandwidth_matrix", "-W3"]
        self._run_command = ["/opt/mlc/Linux/mlc", "-X", "--bandwidth_matrix", "-W3"]
        super().__init__()

    def _repair_instalation(self) -> bool:
        logging.warn("Could not find Intel MLC, installing...")
        if os.path.exists("mlc_v3.11.tgz"):
            os.remove("mlc_v3.11.tgz")
        benchmarks.utils.run_command_simple(
            ["wget", "https://downloadmirror.intel.com/793041/mlc_v3.11.tgz"]
        )
        Path("/opt/mlc").mkdir(parents=True, exist_ok=True)
        benchmarks.utils.run_command_simple(
            ["tar", "-xvf", "mlc_v3.11.tgz", "-C", "/opt/mlc"]
        )
        return True

    def _extract(self, results):
        try:
            return float(re.search(r"([0-9\.]+)[\n\s]*?\Z", results.stdout).group(1))
        except Exception as e:
            print(e)
            return -2


class PerfBenchSyscall(Benchmark):
    def __init__(self):
        self._verify_command = ["perf", "bench", "syscall", "basic", "-l", "1000"]
        self._install_command = [
            "sudo",
            "apt",
            "install",
            "-y",
            "linux-tools-common",
            "linux-tools-generic",
            "linux-tools-`uname -r`",
        ]
        self._run_command = ["perf", "bench", "syscall", "basic", "-l", "5000000"]
        super().__init__()

    def _verify_installation(self) -> bool:
        try:
            # Try to run verify command
            try:
                benchmarks.utils.run_command_simple(self._verify_command)
            # if it doesn't exist install and try again
            except Exception as e:
                print("Installing perf...")
                self._repair_instalation()
                try:
                    benchmarks.utils.run_command_simple(self._verify_command)
                # find the backup command if perf isn't installed properlly, mostly for WSL
                except Exception as e:
                    print("Reverting to failback for perf...")
                    self._verify_command = (
                        f"{glob.glob('/usr/lib/linux-tools/*-generic')[0]}/perf"
                    )
                    self._run_command[0] = self._verify_command
            return True
        # Something has gone seriously wrong, try one more time to install
        except Exception as e:
            print("Perf is broken: ", e)
            pass
        return False

    def _repair_instalation(self) -> bool:
        benchmarks.utils.run_command_simple(["sudo", "apt", "update"])
        benchmarks.utils.run_command_simple(self._install_command, shell=True)

    def _extract(self, results):
        try:
            return float(re.search(r"([0-9\.]*)\s*ops\/sec", results.stdout).group(1))
        except Exception as e:
            print(e)
            return -2


class StressNGCache(Benchmark):

    def __init__(self):
        self._verify_command = ["stress-ng", "--help"]
        self._install_command = ["sudo", "apt", "install", "-y", "stress-ng"]
        self._run_command = [
            "stress-ng",
            "--cache",
            "-1",
            "--no-rand-seed",
            "-t",
            "30s",
            "--metrics-brief",
        ]
        super().__init__()

    def _extract(self, results):
        try:
            return float(re.search(r"([0-9\.]+)[\n\s]*\Z", results.stderr).group(1))
        except Exception as e:
            print(e)
            return -2


class StressNGCpu(Benchmark):

    def __init__(self):
        self._verify_command = ["stress-ng", "--help"]
        self._install_command = ["sudo", "apt", "install", "-y", "stress-ng"]
        self._run_command = [
            "stress-ng",
            "--cpu",
            "-1",
            "--cpu-method",
            "all",
            "--no-rand-seed",
            "-t",
            "30s",
            "--metrics-brief",
        ]
        super().__init__()

    def _extract(self, results):
        try:
            return float(re.search(r"([0-9\.]+)[\n\s]*\Z", results.stderr).group(1))
        except Exception as e:
            print(e)
            return -2


class Fio(Benchmark):

    def __init__(
        self,
        type="randwrite",
        directory="fio",
        batchsize="8K",
        numjobs=1,
        ioengine="libaio",
        runtime=15,
    ):
        self._verify_command = ["fio", "--help"]
        self._install_command = ["sudo", "apt", "install", "-y", "fio"]
        self._run_command = [
            "fio",
            "--name=throughput",
            f"--directory={directory}",
            f"--numjobs={numjobs}",
            "--size=100M",
            "--time_based",
            f"--runtime={runtime}s",
            "--ramp_time=2s",
            f"--ioengine={ioengine}",
            "--direct=1",
            "--verify=0",
            f"--bs={batchsize}",
            f"--rw={type}",
            "--group_reporting=1",
            "--iodepth_batch_submit=64",
            "--iodepth_batch_complete_max=64",
        ]
        benchmarks.utils.run_command_simple(["mkdir", "-p", f"{directory}"])
        super().__init__()

    def _repair_instalation(self) -> bool:
        benchmarks.utils.run_command_simple(["sudo", "apt", "update"])
        benchmarks.utils.run_command_simple(self._install_command)

    def _extract(self, results):
        try:
            return float(re.search(r"bw=([0-9\.]*)", results.stdout).group(1))
        except Exception as e:
            print(e)
            return -2


class Canary(ABC):
    def __init__(self, timer: float = 1, disk_path: str = "."):
        self.thread = threading.Thread(target=self.trigger)

        self.previous: dict[str, object] = {}
        self.fetchers: dict[str, tuple[Callable[[], object], bool]] = {}
        self.columns: list[str] = []

        self.timer: float = timer
        self.disk_path: str = disk_path

        self.running: bool = False

        self._register_metric(
            name="cpu_times", fetch=psutil.cpu_times, incremental=True
        )
        self._register_metric(name="cpu_times_percent", fetch=psutil.cpu_times_percent)
        self._register_metric(
            name="cpu_stats", fetch=psutil.cpu_stats, incremental=True
        )
        self._register_metric(name="cpu_freq", fetch=psutil.cpu_freq)
        self._register_metric(name="virtual_memory", fetch=psutil.virtual_memory)
        self._register_metric(name="swap_memory", fetch=psutil.swap_memory)
        self._register_metric(
            name="disk_io_counters", fetch=psutil.disk_io_counters, incremental=True
        )

    def start(self) -> None:
        self.running = True

        self.data: pd.DataFrame = pd.DataFrame(columns=self.columns)

        # collect all the starting values
        for k, (fetch, incremental) in self.fetchers.items():
            if incremental:
                self.previous[k] = fetch()

        self.thread.start()

    def _fetch_properties(self, result: object):
        return [
            f
            for f in dir(result)
            if not f.startswith("_")
            and (type(getattr(result, f)) is float or type(getattr(result, f)) is int)
        ]

    def _register_metric(
        self, name: str, fetch: Callable[[], object], incremental: bool = False
    ):
        self.fetchers[name] = (fetch, incremental)

        result: object = fetch()
        for prop in self._fetch_properties(result):
            self.columns.append(f"{name} {prop}")

    def trigger(self) -> None:
        while self.running:
            time.sleep(self.timer)

            # add a row
            self.data.loc[len(self.data)] = [np.nan for _ in self.data.columns]
            for name, (fetch, incremental) in self.fetchers.items():
                result: object = fetch()
                for prop in self._fetch_properties(result):
                    value: float = getattr(result, prop)
                    if incremental:
                        value -= getattr(self.previous[name], prop)
                    self.data.loc[self.data.index[-1], f"{name} {prop}"] = value
                self.previous[name] = result

    def stop(self) -> dict[str, float]:
        self.running = False
        self.thread.join()
        return (
            self.data.median().add_suffix(" 50_percentile").to_dict()
            | self.data.quantile(q=0.25).add_suffix(" 25_percentile").to_dict()
            | self.data.quantile(q=0.75).add_suffix(" 75_percentile").to_dict()
        )

        return (
            self.data.mean().add_suffix(" mean").to_dict()
            | self.data.median().add_suffix(" 50_percentile").to_dict()
            | self.data.quantile(q=0.05).add_suffix(" 5_percentile").to_dict()
            | self.data.quantile(q=0.95).add_suffix(" 95_percentile").to_dict()
            | self.data.quantile(q=0.01).add_suffix(" 1_percentile").to_dict()
            | self.data.quantile(q=0.99).add_suffix(" 99_percentile").to_dict()
            | self.data.quantile(q=0.25).add_suffix(" 25_percentile").to_dict()
            | self.data.quantile(q=0.75).add_suffix(" 75_percentile").to_dict()
        )
