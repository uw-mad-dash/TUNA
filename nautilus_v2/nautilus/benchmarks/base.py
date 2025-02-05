import logging
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from functools import cached_property
from pathlib import Path
from subprocess import CompletedProcess

from dacite import from_dict as dataclass_from_dict

from nautilus.config import NautilusConfig
from nautilus.dbms import DBMS
from nautilus.utils import erase_dir, trim_stream_output


@dataclass(frozen=True)
class BenchmarkInfo:
    name: str
    workload: str
    warmup_duration: int = 30  # in seconds
    benchmark_duration: int = 300  # in seconds -- 5 minutes default


class BenchmarkRound(Enum):
    WARMUP = "warmup"
    BENCHMARK = "benchmark"


class Benchmark(ABC):
    """Base (abstract) class for all benchmarks."""

    name: str = None

    # Directory where benchmarks are located
    # NOTE: If change this value, also update the Dockerfile
    INSTALL_DIR = Path("/benchmark")

    # Benchmark info fields
    BENCHMARK_INFO_FIELDS_MAP = {
        "warmup_duration": "__WARMUP_DURATION__",
        "benchmark_duration": "__BENCHMARK_DURATION__",
    }

    # DBMS properties file
    DBMS_PROPERTIES_FIELDS_MAP = {
        "host": "__HOST__",
        "port": "__PORT__",
        "db_name": "__DB_NAME__",
        "user": "__DB_USER__",
        "password": "__DB_PASSWORD__",
        "root_password": "__DB_ROOT_PASSWORD__",
    }

    _rounds_info: dict[BenchmarkRound, dict] = {}
    _perf_stats: dict = {}

    _STD_OUTPUT_CHAR_LIMIT = 500000

    logger: logging.Logger
    _logger_name = ".".join(__name__.split(".")[:-1])  # hide .base

    def __init__(self, dbms: DBMS, info: BenchmarkInfo):
        if self.name is None:
            raise ValueError("Benchmark name should NOT be None")

        self.dbms = dbms
        self.info = info
        self.workload = info.workload

        self.measurements_dirpath = (
            NautilusConfig.get().disk_backup_mount_point.local / "measurements"
        )

    @abstractmethod
    def init(self):
        """Update the configuration and prepare the commands to run"""
        raise NotImplementedError

    @abstractmethod
    def load(self):
        """Execute the loading of the data to the DBMS"""
        raise NotImplementedError

    @abstractmethod
    def run(self, round: BenchmarkRound):
        """Execute the benchmark"""
        raise NotImplementedError

    def prepare_init_db_directory(self, workspace_dir: Path) -> Path | None:
        """Prepare the init-db directory used to create the database"""
        if self.init_db_dir is None:
            return None

        # Copy init-db directory to workspace
        subpath = self.init_db_dir.relative_to(self.conf_dir)
        target_dir = workspace_dir / subpath
        if target_dir.exists():
            erase_dir(target_dir)
        shutil.copytree(self.init_db_dir, target_dir, dirs_exist_ok=True)

        return subpath

    @property
    def run_info(self):
        return self._rounds_info

    @property
    def perf_stats(self):
        if not self._perf_stats:
            self._perf_stats = self._parse_perf_stats()
        return self._perf_stats

    @cached_property
    def benchmark_dir(self):
        """Retrieve directory where benchmark is installed (i.e., /benchmark/<name>)"""
        dirpath = self.INSTALL_DIR / self.name
        if not dirpath.exists():
            raise FileNotFoundError(
                f"Cannot find installation for {self.name} [@{dirpath}]"
                f"Is {self.name} really installed?"
            )

        self.logger.info(f"Benchmark install directory: {dirpath}")
        return dirpath

    @cached_property
    def conf_dir(self):
        """Retrieve (local) benchmark configuration directory"""
        current_dir = Path(__file__).parent
        dirpath = (current_dir / self.name).resolve()
        if not dirpath.exists():
            raise FileNotFoundError(
                f"Benchmark (local) config dir does not exist [@{dirpath}]"
            )

        self.logger.info(f"Benchmark conf directory: {dirpath}")
        return dirpath

    @cached_property
    def init_db_dir(self):
        """Retrieve (local) benchmark init-db directory"""
        dirpath = self.conf_dir / self.dbms.name / "init-db"
        if not dirpath.exists():
            self.logger.info(
                f"Benchmark init-db directory not found @[{dirpath}]. "
                "Would need to explicitly create database!"
            )
            return None

        self.logger.info(f"Benchmark `{self.dbms.name}' init-db directory: {dirpath}")
        return dirpath

    @abstractmethod
    def _parse_perf_stats(self):
        raise NotImplementedError

    def _substitute_template_values(
        self, template: str, mapper_dict: dict[str, str], values
    ) -> str:
        """Substitute template placeholders with provided values"""
        contents = template
        for name, placeholder in mapper_dict.items():
            try:  # values is obj?
                value = getattr(values, name)
            except:  # noqa: E722
                try:  # values is indexable?
                    value = values[name]
                except:  # noqa: E722
                    raise RuntimeError(
                        f'Cannot find "{name}" value to '
                        f"substitute [{placeholder}] in template"
                    )

            # Replace placeholder with value
            contents = contents.replace(placeholder, str(value))

        return contents

    def _handle_run_process_outcome(
        self,
        round: BenchmarkRound,
        cp: CompletedProcess | None,
        start: datetime,
        end: datetime,
    ) -> None:
        """Handle the outcome of a run process.

        This is called by the `run` method to check for failures
        and to build & store the runtime information.
        """

        # Check cp return value
        if cp is not None:
            if cp.returncode == 0:
                self.logger.info(f"Round '{round.value}' finished successfully! :)")
            else:
                self.logger.warning(
                    f"Round '{round.value}' failed! Returned code {cp.returncode} :/"
                )
            result = "ok" if cp.returncode == 0 else "failed"
        else:
            self.logger.error(f"Round '{round.value}' failed! Check logs.")
            result = "failed"

        # Elapsed time
        elapsed = (end - start).total_seconds()
        self.logger.info(f"Round '{round.value}' took {elapsed:.2f} seconds")

        # Store runtime data
        runtime_info = {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "elapsed": elapsed,
            "stdout": cp.stdout if cp is not None else "",
            "stderr": cp.stderr if cp is not None else "",
            "returncode": cp.returncode if cp is not None else None,
            "result": result,
        }

        if len(cp.stderr) > 0:
            self.logger.warning(f"Written to stderr: {cp.stderr}")

        # Trim size of stdout and stderr (if needed)
        # NOTE: This is to avoid large outputs in the logs
        for ss in ["stdout", "stderr"]:
            runtime_info[ss] = trim_stream_output(runtime_info[ss], stream_name=ss)

        self._rounds_info[round.value] = runtime_info

    @classmethod
    def from_info(class_, dbms: DBMS, info: dict) -> "Benchmark":
        """Factory method to create a Benchmark instance from info dict"""
        class_, info_dc = class_._get_cls_and_info(info)
        return class_(dbms, info_dc)

    @staticmethod
    def _get_cls_and_info(info: dict) -> tuple["Benchmark", BenchmarkInfo]:
        """Retrieve derived Benchmark class and info dataclass from info dict"""
        name = info["name"]

        from nautilus.benchmarks.ycsb import YCSB, YCSBBenchmarkInfo
        from nautilus.benchmarks.benchbase import BenchBase, BenchBaseInfo
        from nautilus.benchmarks.wrk import Wrk, WrkBenchmarkInfo

        AVAILABLE_BENCHMARKS = {
            "ycsb": (YCSB, YCSBBenchmarkInfo),
            "benchbase": (BenchBase, BenchBaseInfo),
            "wrk": (Wrk, WrkBenchmarkInfo),
        }

        try:
            class_, info_dc_cls = AVAILABLE_BENCHMARKS[name]
        except KeyError:
            error_msg = f"ERROR: Benchmark [`{name}`] not found :("
            print(error_msg)
            raise ValueError(error_msg)

        return class_, dataclass_from_dict(info_dc_cls, info)
