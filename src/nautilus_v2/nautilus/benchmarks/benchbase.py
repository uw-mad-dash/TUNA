import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from functools import cached_property
from glob import glob
from pathlib import Path
from string import Template
from subprocess import PIPE

import numpy as np
import pandas as pd
import xmltodict

from nautilus.benchmarks import Benchmark, BenchmarkInfo, BenchmarkRound
from nautilus.utils import disk_sync, run_command, erase_dir

@dataclass(frozen=True, eq=False)
class BenchBaseWorkloadProperties:
    scalefactor: int = 20       # related to size of DB / number of tuples
    terminals:   int = 40       # number of concurrent requests (# threads)
    work_rate:   int | str = 'unlimited'# pylint: disable=unsubscriptable-object
    batch_size:  int = 16384    # number of INSERT SQL statements batched together, during loading phase

    def __eq__(self, o):
        # all (except `scalefactor`) are runtime parameters
        return self.scalefactor == o.scalefactor

@dataclass(frozen=True)
class BenchBaseInfo(BenchmarkInfo):
    workload_properties: BenchBaseWorkloadProperties = \
        field(default_factory=BenchBaseWorkloadProperties)

    parse_raw_perf_stats: bool = False
    parse_per_transaction_perf_stats: bool = False

class BenchBase(Benchmark):
    name = 'benchbase'

    # Workload descriptor file & workload properties map
    workload_descriptor_template_filename = '${workload}.xml.template'
    workload_descriptor_filename = '${workload}.xml' # after replacing values
    workload_properties_fields_map = {
        'scalefactor': '__SCALE_FACTOR__',
        'terminals': '__TERMINALS__',
        'work_rate': '__RATE__',
        'batch_size': '__BATCH_SIZE__',
    }
    # Extra JDBC-related info that need to be passed to BenchBench
    dbms_jdbc_fields_map = {
        'db_type': '__DB_TYPE__',
        'jdbc_driver': '__DB_JDBC_DRIVER__',
        'jdbc_subprotocol': '__DB_JDBC_SUBPROTOCOL__',
        'jdbc_isolation_level': '__CONN_ISOLATION_LEVEL__',
        'jdbc_url_suffix': '__URL_SUFFIX__',
    }

    def __init__(self, dbms, info):
        self.logger = logging.getLogger(self._logger_name)
        self.logger.info(f'BenchBase for {dbms.name} DBMS')

        super().__init__(dbms, info) # self.workload stores the benchmark class

        # Construct target directory for workload description files
        self.target_workloads_dir = self.benchmark_dir / 'workloads'
        if not self.target_workloads_dir.exists():
            self.logger.info(f'Creating directory "{self.target_workloads_dir}"')
            self.target_workloads_dir.mkdir()

        # Retrieve workload descriptor file definition
        # TODO: add a special "custom" value if the user wants to
        #       provide their own workload descriptor template
        self.workload_descriptor_template_filename = (
            Template(self.workload_descriptor_template_filename)
                .substitute(workload=self.workload))
        self.workload_descriptor_filename = (
            Template(self.workload_descriptor_filename)
                .substitute(workload=self.workload))

        # Read workload descriptor template
        workload_descriptor_template_filepath = (
            self.conf_dir / 'workloads' / self.workload_descriptor_template_filename)
        try:
            with open(workload_descriptor_template_filepath, 'r') as f:
                self.workload_descriptor_template = f.read()
        except OSError as err:
            raise FileNotFoundError(
                'Cannot read BenchBase workload descriptor template file'
                f'[@ {workload_descriptor_template_filepath}]: {repr(err)}')

    @cached_property
    def benchmark_dir(self):
        """ Retrieve directory where benchmark is installed """
        dirpath = Path('/benchmark') / f'{self.name}-{self.dbms.name}'
        if not dirpath.exists():
            raise FileNotFoundError(
                f'Cannot find installation for {self.name} [@{dirpath}]'
                f'Is {self.name} really installed?')

        self.logger.info(f'Benchmark install directory: {dirpath}')
        return dirpath

    def init(self):
        """ Update the configuration and prepare the commands to run """

        # JDBC template variables
        jdbc_fields_values = {
            'db_type': self.dbms.name,
            'jdbc_driver': self.dbms.driver_jar_properties['name'],
            'jdbc_subprotocol': self.dbms.driver_jar_properties['subprotocol'],
            'jdbc_isolation_level': self.dbms.driver_jar_properties['isolation_level'].name,
            'jdbc_url_suffix': self.dbms.driver_jar_properties['url_suffix'],
        }
        # Render template by replacing values
        def render_template(template, fields_map_values_pairs):
            for fields_map, values in fields_map_values_pairs:
                template = self._substitute_template_values(
                    template, fields_map, values)
            return template

        fields_map_values_pairs = [
            (self.dbms_jdbc_fields_map, jdbc_fields_values),
            (self.DBMS_PROPERTIES_FIELDS_MAP, self.dbms),
            (self.BENCHMARK_INFO_FIELDS_MAP, self.info),
            (self.workload_properties_fields_map, self.info.workload_properties)
        ]
        workload_descriptor_contents = render_template(
            self.workload_descriptor_template, fields_map_values_pairs)

        # Write workload descriptor file
        self.workload_descriptor_filepath = (
            self.target_workloads_dir / self.workload_descriptor_filename)
        with open(self.workload_descriptor_filepath, 'w') as f:
            f.write(workload_descriptor_contents)

        self.benchbase_benchmark_name = self.workload
        if self.benchbase_benchmark_name.startswith('ycsb'):
            # ycsbA, ycsbB, ...
            self.benchbase_benchmark_name = 'ycsb'

    def load(self):
        """ Execute the loading of the data to the DBMS """

        # Create schema and load data
        command = (f'cd {self.benchmark_dir} && '
            f'java -jar benchbase.jar -b {self.benchbase_benchmark_name} '
            f'--create=true --load=true '
            f'-c {self.workload_descriptor_filepath}')

        self.logger.info('Creating databases & loading data...')
        cp = run_command(command,
                stdout=PIPE, stderr=PIPE, encoding='utf-8', check=True)
        if cp is None:
            self.logger.error('Creating database & loading data failed!')
            raise RuntimeError('BenchBase load failed!')

        self.logger.info('Database created & data loaded!')

        # Ensure that the data is written to disk
        disk_sync(container_name=self.dbms.host)

        return {
            'stdout': cp.stdout,
            'stderr': cp.stderr,
        }

    def run(self, round: BenchmarkRound):
        """ Execute the benchmark """

        if round is BenchmarkRound.WARMUP:
            # NOTE: BenchBase has embedded the warm-up round with the benchmark one
            self.logger.info('BenchBase cannot run warm-up round separately. '
                             "Setting `run_info' warmup entry to empty and skipping...")
            self._rounds_info[round.value] = {
                'start': None,
                'end': None,
                'elapsed': 0.0,

                'stdout': '',
                'stderr': '',
                'returncode': 0,
                'result': None,
            }
            return self._rounds_info[round.value]

        # Create directory to store measurements (remove leftovers if exists)
        if self.measurements_dirpath.exists():
            try:
                erase_dir(self.measurements_dirpath)
            except Exception as err:
                error_message = ('Error while trying to delete folder '
                                f'@[{self.measurements_dirpath}]: {str(err)}')
                self.logger.error(error_message)
                raise RuntimeError(error_message)
        self.measurements_dirpath.mkdir()

        # Prepare command
        cmd = (f'cd {self.benchmark_dir} && '
            f'java -jar benchbase.jar -b {self.benchbase_benchmark_name} '
            f'--execute=true '
            f'-c {self.workload_descriptor_filepath} '
            f'-d {self.measurements_dirpath} '
            f'-s 1') # summarize (latency, throughput) every 1 sec
        self.logger.info(f"Starting `{round.value}' round...")

        start = datetime.now()
        cp = run_command(cmd,
            stdout=PIPE, stderr=PIPE, encoding='utf-8', check=True)
        end = datetime.now()

        self._handle_run_process_outcome(round, cp, start, end)
        return self._rounds_info[round.value]

    def _parse_perf_stats(self) -> dict:
        """ Parse BenchBase measurements and return them as a dictionary """
        perf_stats = { 'name': 'benchbase' }
        self.logger.info(f'Parsing BenchBase measurements [{self.measurements_dirpath.as_posix()}]...')

        # Define files to parse (key_suffix, filename_suffix)
        perf_stats_files_info = {
            'config': '.config.xml',
            'results': '.results.csv',
            'samples': '.results.csv',
            'params': '.params.json',
            'summary': '.summary.json',
        }
        if self.info.parse_raw_perf_stats:
            perf_stats_files_info['raw'] = '.raw.csv'
        if self.info.parse_per_transaction_perf_stats:
            try:
                # Retrieve transaction names from workload descriptor template
                template_dict = xmltodict.parse(self.workload_descriptor_template)
                transaction_names = [ e['name']
                    for e in template_dict['parameters']['transactiontypes']['transactiontype']]
            except Exception as err:
                self.logger.error(f'While retrieving workload transactions: {repr(err)}')
                self.logger.info('Skipping per-transaction measurements parsing')
            else:
                # Add transaction names to perf_stats_files_info
                for t in transaction_names:
                    key = f'results.{t}'
                    perf_stats_files_info[key] = f'.{key}.csv'

        def get_measurements_filepath(file_list: list, suffix: str) -> Path | None:
            for f in file_list:
                if f.endswith(suffix):
                    return Path(f)

            self.logger.warning(f"Returning `None' for '{suffix}' measurements filepath."
                            f"Does the file exist? [all-files: {', '.join(file_list)}]")
            return None

        # Parse raw & samples measurements
        file_list = list(glob(f'{self.measurements_dirpath}/*'))

        for key_suffix, fn_suffix in perf_stats_files_info.items():
            self.logger.info(f'Parsing {key_suffix} results...')

            key = f'benchbase_{key_suffix}'
            fp = get_measurements_filepath(file_list, fn_suffix)

            try:
                if fp.as_posix().endswith('.csv'): # read csv
                    perf_stats[key] = \
                        pd.read_csv(fp).rename(columns=lambda x: x.strip())
                elif fp.as_posix().endswith('.json'): # read json
                    with open(fp, 'r') as f:
                        perf_stats[key] = json.load(f)
                else: # read raw file
                    with open(fp, 'r') as f:
                        perf_stats[key] = f.read()

            except Exception as err:
                if fp is None:
                    error_msg = f"No file found for `{key_suffix}' measurements. Skipping!"
                    self.logger.warning(error_msg)
                else:
                    error_msg = repr(err)
                    self.logger.exception(
                        f'While parsing BenchBase {key_suffix} measurements: {error_msg}')

                perf_stats[f'{key}_error_msg'] = error_msg

            finally:
                if key not in perf_stats:
                    perf_stats[key] = None
                perf_stats[f'{key}_result'] = (
                    'ok' if perf_stats[key] is not None else 'error')

        # Compute summary metrics from
        summarize_func = {
            'Time (seconds)': np.max,
            'Throughput (requests/second)': np.mean,
            'Average Latency (millisecond)': np.mean,
            'Minimum Latency (millisecond)': np.mean,
            '25th Percentile Latency (millisecond)': np.mean,
            'Median Latency (millisecond)': np.mean,
            '75th Percentile Latency (millisecond)': np.mean,
            '90th Percentile Latency (millisecond)': np.mean,
            '95th Percentile Latency (millisecond)': np.mean,
            '99th Percentile Latency (millisecond)': np.mean,
            'Maximum Latency (millisecond)': np.max,
            'tp (req/s) scaled': np.mean,
        }
        self.logger.debug('Computing results summary results...')

        try:
            perf_stats['benchmark_results'] = {
                k: func(perf_stats['benchbase_results'][k]).item()
                for k, func in summarize_func.items()
            }
        except Exception as err:
            perf_stats['benchmark_results_error_msg'] = repr(err)
            self.logger.exception(
                f'While parsing BenchBase results summary measurements: {repr(err)}')
        finally:
            if 'benchmark_results' not in perf_stats:
                perf_stats['benchmark_results'] = None
            perf_stats['benchmark_results'] = (
                'ok' if perf_stats['benchmark_results'] is not None else 'error')

        # Convert dataframe to dictionary-like form (objects)
        for key_suffix, _ in perf_stats_files_info.items():
            key = f'benchbase_{key_suffix}'
            if key not in perf_stats or not isinstance(perf_stats[key], pd.DataFrame):
                    continue
            perf_stats[key] = perf_stats[key].to_dict(orient='records')

        return perf_stats
