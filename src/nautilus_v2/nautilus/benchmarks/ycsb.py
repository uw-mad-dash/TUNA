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
from nautilus.dbms import DBMS
from nautilus.utils import disk_sync, run_command, trim_stream_output

# YCSB bindings for each DBMS
# NOTE: These exist inside /benchmark/ycsb/lib
DBMS_BINDING_MAP = {
    "cassandra": "cassandra-cql",
    "mysql": "jdbc",
    "postgres": "jdbc",
    "redis": "redis",
}


@dataclass(frozen=True, eq=False)
class YCSBWorkloadProperties:
    recordcount: int = 20_000_000  # 20 GiB database
    operationcount: int = 20_000_000  # 20M ops
    threadcount: int = 40

    def __eq__(self, o):
        return self.recordcount == o.recordcount


@dataclass(frozen=True)
class YCSBBenchmarkInfo(BenchmarkInfo):
    workload_properties: YCSBWorkloadProperties = field(
        default_factory=YCSBWorkloadProperties
    )


class YCSB(Benchmark):
    name = "ycsb"

    # DBMS properties file
    DB_PROPERTIES_TEMPLATE_FILENAME = "db.properties.template"
    DB_PROPERTIES_FILENAME = "db.properties"

    # YCSB run type file
    RUN_ROUND_PROPERTIES_TEMPLATE_FILENAME = "run_${round}.template"
    RUN_ROUND_PROPERTIES_FILENAME = "run_${round}"

    # Workload properties file
    WORKLOAD_PROPERTIES_TEMPLATE_FILENAME = "workload_properties.template"
    WORKLOAD_PROPERTIES_FILENAME = "workload_properties"  # after replacing values
    WORKLOAD_PROPERTIES_FIELDS_MAP = {
        "recordcount": "__RECORD_COUNT__",
        "operationcount": "__OPERATION_COUNT__",
        "threadcount": "__THREAD_COUNT__",
    }

    dbms_binding: str

    def __init__(self, dbms: DBMS, info: YCSBBenchmarkInfo) -> None:
        self.logger = logging.getLogger(self._logger_name)
        self.logger.info(f"YCSB benchmark for DBMS: {dbms.name}")

        super().__init__(dbms, info)

        # Filepath where YCSB executor measurements will be saved
        self.measurements_dirpath.mkdir(parents=True, exist_ok=True)
        self.raw_measurements_filepath = self.measurements_dirpath / "raw_ycsb"

        # Check that workload exists in YCSB workloads dir
        workload_path = self.conf_dir / "workloads" / info.workload
        if not workload_path.exists():
            raise ValueError(
                f"Invalid workload `{info.workload}' -- Path `{workload_path.as_posix()}' does not exist"
            )
        self.workload_path = workload_path

        # Store info.workload_properties
        self.workload_properties = info.workload_properties

        # Retrieve the YCSB binding class for this DBMS
        try:
            self.dbms_binding = DBMS_BINDING_MAP[self.dbms.name]
        except KeyError:
            raise KeyError(f"YCSB Binding for `{self.dbms.name}' not defined")

        # Paths corresponding to YCSB's installation directory
        self.ycsb_conf_dir = self.benchmark_dir / "conf"
        self.ycsb_lib_dir = self.benchmark_dir / "lib"
        self.ycsb_workloads_dir = self.benchmark_dir / "workloads"

        ## DBMS properties
        ## NOTE: These are used to customize DBMS-related properties (e.g., host, port, etc.)
        # Read DBMS properties template file contents
        db_properties_template_filepath = (
            self.conf_dir / self.dbms.name / self.DB_PROPERTIES_TEMPLATE_FILENAME
        )
        try:
            with open(db_properties_template_filepath, "r") as f:
                self.db_properties_template = f.read()
        except OSError as err:
            self.logger.error(
                "Cannot read YCSB DB properties template file contents"
                f"[@ {db_properties_template_filepath}]: {repr(err)}"
            )
            raise

        ## Workload properties
        ## NOTE: These are used to customize workload-related properties
        # (e.g., recordcount, operationcount, etc.)
        # Read workload properties template file contents
        workload_properties_template_filepath = (
            self.conf_dir / "workloads" / self.WORKLOAD_PROPERTIES_TEMPLATE_FILENAME
        )
        try:
            with open(workload_properties_template_filepath, "r") as f:
                self.workload_properties_template = f.read()
        except OSError as err:
            self.logger.error(
                "Cannot read YCSB workload properties template file contents"
                f"[@ {workload_properties_template_filepath}]: {repr(err)}"
            )
            raise

        ## Run type properties
        ## NOTE: These are used to customize run type-related properties
        # (e.g., warmup/benchmark duration, etc.)

        # Retrieve run type property file definitions
        filenames: dict[str, str] = {}
        template_filenames: dict[str, str] = {}
        for br in BenchmarkRound:
            round: str = br.value
            template_filenames[round] = Template(
                self.RUN_ROUND_PROPERTIES_TEMPLATE_FILENAME
            ).substitute(round=round)
            filenames[round] = Template(self.RUN_ROUND_PROPERTIES_FILENAME).substitute(
                round=round
            )

        self.run_rounds_properties_template_filename = template_filenames
        self.run_rounds_properties_filename = filenames

        # Read run type properties template file contents
        self.run_rounds_properties_template = {}
        for br in BenchmarkRound:
            round = br.value
            run_round_properties_template_filepath = (
                self.conf_dir
                / "workloads"
                / self.run_rounds_properties_template_filename[round]
            )
            try:
                with open(run_round_properties_template_filepath, "r") as f:
                    self.run_rounds_properties_template[round] = f.read()
            except OSError as err:
                self.logger.error(
                    f"Cannot read YCSB run type properties template file contents"
                    f"[@ {run_round_properties_template_filepath}]: {repr(err)}"
                )
                raise

    def init(self):
        """Update the configuration and prepare the commands to run"""

        # Copy DBMS jarfile to YCSB library dir (if exists)
        if self.dbms.driver_jar_filepath is not None:
            shutil.copy(self.dbms.driver_jar_filepath, self.ycsb_lib_dir)

        ## DBMS properties file
        # Customize db properties (i.e. replace values from template)
        db_properties_contents = self._substitute_template_values(
            self.db_properties_template, self.DBMS_PROPERTIES_FIELDS_MAP, self.dbms
        )
        # Write db properties file contents to YCSB installation conf path
        db_properties_filepath = self.ycsb_conf_dir / self.DB_PROPERTIES_FILENAME
        with open(db_properties_filepath, "w") as f:
            f.write(db_properties_contents)

        ## Run type properties file
        for br in BenchmarkRound:
            round = br.value
            # Customize run type properties (i.e. replace values from template)
            run_round_properties_contents = self._substitute_template_values(
                self.run_rounds_properties_template[round],
                self.BENCHMARK_INFO_FIELDS_MAP,
                self.info,
            )
            run_round_properties_contents = run_round_properties_contents.replace(
                "__RAW_MEASUREMENTS_FILEPATH__",
                self.raw_measurements_filepath.as_posix(),
            )
            # Write run type properties file contents to YCSB installation workload path
            run_round_properties_filepath = (
                self.ycsb_workloads_dir / self.run_rounds_properties_filename[round]
            )
            with open(run_round_properties_filepath, "w") as f:
                f.write(run_round_properties_contents)

        ## Workload properties file
        # Customize workload properties (i.e. replace values from template)
        workload_properties_contents = self._substitute_template_values(
            self.workload_properties_template,
            self.WORKLOAD_PROPERTIES_FIELDS_MAP,
            self.workload_properties,
        )
        # Write workload properties file contents to YCSB installation workload path
        workload_properties_filepath = (
            self.ycsb_workloads_dir / self.WORKLOAD_PROPERTIES_FILENAME
        )
        with open(workload_properties_filepath, "w") as f:
            f.write(workload_properties_contents)

        ## Copy workload to YCSB workload path
        shutil.copy(self.workload_path, self.ycsb_workloads_dir)

    def load(self):
        """Execute the loading of the data to the DBMS"""

        # Load data
        cmd = (
            f"cd {self.benchmark_dir} && "
            f"./bin/ycsb.sh load {self.dbms_binding}"
            f" -P conf/{self.DB_PROPERTIES_FILENAME}"
            f" -P workloads/{self.WORKLOAD_PROPERTIES_FILENAME}"
            f" -P workloads/{self.workload}"
        )

        self.logger.info("Loading data...")
        cp = run_command(cmd, stdout=PIPE, stderr=PIPE, encoding="utf-8", check=True)
        if cp is None:
            self.logger.error("Loading data failed!")
            raise RuntimeError("YCSB load failed!")

        # Ensure data have persisted
        disk_sync(container_name=self.dbms.host)

        load_info = {
            "stdout": cp.stdout if cp else "",
            "stderr": cp.stderr if cp else "",
        }
        for ss, v in load_info.items():
            load_info[ss] = trim_stream_output(v, stream_name=ss)

        return load_info

    def run(self, round: BenchmarkRound):
        """Execute the benchmark"""

        # Remove previous metrics file
        # Default YCSB behavior is appending new metrics to end-of-file
        if self.raw_measurements_filepath.exists():
            self.logger.debug(
                f"Deleting previous YCSB measurements file: "
                f"[@{self.raw_measurements_filepath}]"
            )
            self.raw_measurements_filepath.unlink()

        # Prepare command and run
        cmd = (
            f"cd {self.benchmark_dir} && JAVA_OPTS='-d64 -Xmx6g' && "
            f"./bin/ycsb.sh run {self.dbms_binding}"
            f" -P conf/{self.DB_PROPERTIES_FILENAME}"
            f" -P workloads/{self.WORKLOAD_PROPERTIES_FILENAME}"
            f" -P workloads/{self.run_rounds_properties_filename[round.value]}"
            f" -P workloads/{self.workload}"
        )
        self.logger.info(f"Starting {round.value} round...")

        start = datetime.now()
        cp = run_command(cmd, stdout=PIPE, stderr=PIPE, encoding="utf-8")
        end = datetime.now()

        self._handle_run_process_outcome(round, cp, start, end)
        return self._rounds_info[round.value]

    def _parse_perf_stats(self):
        perf_stats = {"name": "ycsb"}

        parser = YCSBParser()

        # Parse YCSB metrics
        try:
            perf_stats["ycsb"] = parser.parse_measurements(
                self.run_info["benchmark"]["stdout"], data_type="histogram"
            )
        except Exception as err:
            error_msg = repr(err)
            perf_stats["ycsb_error_msg"] = error_msg
            self.logger.exception(f"While parsing YCSB measurements: {error_msg}")
            if "ycsb" not in perf_stats:
                perf_stats["ycsb"] = None
        finally:
            perf_stats["ycsb_result"] = "ok" if perf_stats["ycsb"] else "error"

        # Parse YCSB raw metrics
        try:
            perf_stats["ycsb_raw"] = parser.parse_raw_measurements(
                self.raw_measurements_filepath.as_posix(), perf_stats["ycsb"]
            )
        except Exception as err:
            error_msg = repr(err)
            perf_stats["ycsb_raw_error_msg"] = error_msg
            self.logger.exception(f"While parsing YCSB raw measurements: {error_msg}")
            if "ycsb_raw" not in perf_stats:
                perf_stats["ycsb_raw"] = None
        finally:
            perf_stats["ycsb_raw_result"] = "ok" if perf_stats["ycsb_raw"] else "error"

        del parser
        return perf_stats


class YCSBParser:
    """YCSB output/results parsing class"""

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)

        self.PERCENTILES = list(map(float, range(1, 101))) + [
            99.5,
            99.9,
            99.95,
            99.99,
            99.995,
            99.999,
        ]
        self.PERCENTILES_STR = [f"p{p}" for p in range(1, 101)] + [
            "p99.5",
            "p99.9",
            "p99.95",
            "p99.99",
            "p99.995",
            "p99.999",
        ]

    def parse_raw_measurements(self, filepath: Path, measurements: dict) -> dict:
        """Reads and parses YCSB's more fine-grained measurements"""
        # Try to get groups from YCSB measurements
        try:
            groups = [g for g in measurements["groups"].keys() if g != "overall"]
        except:  # noqa: E722
            # Otherwise use all groups
            groups = ["read", "update", "scan", "insert", "read-write-modify"]

        # Read and parse raw measurements
        values = {g: [] for g in groups}
        with open(filepath, "r") as csvfile:
            lines = csv.reader(csvfile, delimiter=",")
            for parts in lines:
                op, latency = parts[0].strip().lower(), parts[2].strip()
                if op not in groups:
                    continue

                values[op].append(int(latency))

        # Compute latency percentile values for each group
        latencies = {}
        for g, v in values.items():
            if len(v) == 0:
                self.logger.warning(f"Group `{g}' does not contain any values :/")
                continue

            lat_percentile = np.percentile(v, self.PERCENTILES).tolist()
            latencies[g] = dict(zip(self.PERCENTILES_STR, lat_percentile))

        return {
            **{"percentiles": self.PERCENTILES},
            "latencies": latencies,
        }

    def parse_measurements(self, stdout: str, data_type: str = "histogram") -> dict:
        """
        Args:
            ycsb_result_string: str. Text output from YCSB.
            data_type: Either 'histogram' or 'timeseries' or 'hdrhistogram'.
            'histogram' and 'hdrhistogram' datasets are in the same format,
            with the difference being lacking the (millisec, count) histogram
            component. Hence are parsed similarly.

        Returns:
            A dictionary with keys:
            client: containing YCSB version information.
            command_line: Command line executed.
            groups: list of operation group descriptions, each with schema:
                group: group name (e.g., update, insert, overall)
                statistics: dict mapping from statistic name to value
                histogram: list of (ms_lower_bound, count) tuples, e.g.:
                [(0, 530), (19, 1)]
                indicates that 530 ops took between 0ms and 1ms, and 1 took
                between 19ms and 20ms. Empty bins are not reported.
        Raises:
            IOError: If the results contained unexpected lines.
        """
        lines = []
        client_string = "YCSB"
        command_line = "unknown"
        fp = StringIO(stdout)
        stdout = next(fp).strip()

        def IsHeadOfResults(line):
            return line.startswith("[OVERALL]")

        while not IsHeadOfResults(stdout):
            if stdout.startswith("YCSB Client 0."):
                client_string = stdout
            if stdout.startswith("Command line:"):
                command_line = stdout
            try:
                stdout = next(fp).strip()
            except StopIteration:
                raise IOError("Could not parse YCSB output: {}".format(stdout))

        if stdout.startswith("[OVERALL]"):  # YCSB > 0.7.0.
            lines.append(stdout)
        else:
            # Received unexpected header
            raise IOError("Unexpected header: {0}".format(client_string))

        # Some databases print additional output to stdout.
        # YCSB results start with [<OPERATION_NAME>];
        # filter to just those lines.
        def LineFilter(line):
            return re.search(r"^\[[A-Z]+\]", line) is not None

        lines = itertools.chain(lines, filter(LineFilter, fp))
        r = csv.reader(lines)
        by_operation = itertools.groupby(r, operator.itemgetter(0))

        result = {
            "client": client_string,
            "command_line": command_line,
            "groups": {},
        }
        for operation, lines in by_operation:
            operation = operation[1:-1].lower()

            if operation == "cleanup":
                continue

            op_result = {
                "group": operation,
                "statistics": {},
                data_type: [],
            }

            latency_unit = "ms"
            for _, name, val in lines:
                name, val = name.strip(), val.strip()
                # Drop ">" from ">1000"
                if name.startswith(">"):
                    name = name[1:]

                val = float(val) if "." in val or "nan" in val.lower() else int(val)
                if name.isdigit():
                    if val:
                        if data_type == "timeseries" and latency_unit == "us":
                            val /= 1000.0
                        op_result[data_type].append((int(name), val))
                else:
                    if "(us)" in name:
                        name = name.replace("(us)", "(ms)")
                        val /= 1000.0
                        latency_unit = "us"
                    op_result["statistics"][name] = val

            result["groups"][operation] = op_result

        return result
