import logging
import os
import subprocess
import shutil
from datetime import datetime
from time import sleep

import ray
from pympler import asizeof

from nautilus.benchmarks import Benchmark, BenchmarkRound
from nautilus.common import PathPair
from nautilus.config import NautilusConfig
from nautilus.dbms import DBMS, DBMSConfigType
from nautilus.storage import DatabaseStorageManager
from nautilus.samplers.controller import SamplersController
from nautilus.utils import (
    clear_system_caches,
    disk_sync,
    erase_dir,
    report_and_return_error,
    trim_stream_output,
    update_environ,
)

# NautilusConfig
# NOTE: Cannot initialize in module level,
#       as Ray's multithreading causes issues.
config: NautilusConfig = None


@ray.remote(num_cpus=1)
class RunDBMSConfiguration:

    def __init__(self):
        # Initialize logging
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s\t%(levelname)s [%(name)s] %(filename)s:%(lineno)s -- %(message)s",
        )
        self.logger = logging.getLogger(__name__)

        # Load configuration
        global config
        try:
            config = NautilusConfig.init()
        except Exception as err:
            raise RuntimeError(f"Error while loading configuration: {repr(err)}")
        else:
            config.create_local_dirs()
            # Update environment variables
            update_environ(config.config.env)

        self.db_storage_manager = DatabaseStorageManager(
            config.disk_backup_mount_point, num_slots=3, clear_dir=True
        )

    def run_command(self, dbms_info_dict: dict, command: str, params: list):
        self.dbms = DBMS.from_info(config.dbms, dbms_info_dict)
        try:
            result = self.dbms.run_command(command, params)
        except Exception as e:
            self.logger.error(f"Error running command: {command}: {repr(e)}")
            result = []
        return result

    def load(
        self,
        dbms_info_dict: dict,
        benchmark_info_dict: dict,
        samplers_info: dict | None = None,
        _debug=False,
    ) -> dict:
        """Evaluate a DBMS configuration on the given benchmark"""

        self.logger.info(
            f"Received new task args:\n"
            f"{dbms_info_dict =}\n"
            f"{benchmark_info_dict =}\n"
            f"{samplers_info =}"
        )

        # Initialize DBMS & benchmark classes
        self.dbms = DBMS.from_info(config.dbms, dbms_info_dict)
        self.benchmark = Benchmark.from_info(self.dbms, benchmark_info_dict)
        # Initialize samplers
        self.samplers = SamplersController(self.dbms, samplers_info)

        # Initial experiment entry
        result = {
            "task_args": {
                "dbms": dbms_info_dict,
                "benchmark": benchmark_info_dict,
                "samplers": samplers_info,
            },
            "node": os.environ.get("HOSTNAME", "worker"),
            "start": datetime.now().isoformat(),
        }
        dbms_info, benchmark_info = self.dbms.info, self.benchmark.info

        # Stop potential previously running dbms container
        self.dbms.stop(raise_if_not_found=False)

        # Init benchmark
        self.benchmark.init()

        # Prepare init-db directory (i.e., copy init-db scripts to dir accessible from host)
        relative_path = self.benchmark.prepare_init_db_directory(
            config.workspace_dir.local
        )
        # Set host path of benchmark init-db directory
        os.environ["DB_INIT_DIR"] = (
            config.workspace_dir.host / relative_path
            if relative_path
            else config.empty_dir.host
        ).as_posix()

        os.environ["HOST_DIR"] = (config.workspace_dir.host).as_posix()

        # Retrieve entry from storage manager (or allocate new one if not found)
        try:
            self.db_data_dirpath = self.db_storage_manager.get_entry(
                dbms_info, benchmark_info
            )

            if self.db_data_dirpath is None:
                # Allocate entry
                self.db_data_dirpath = self.db_storage_manager.allocate_entry(
                    dbms_info, benchmark_info
                )
                # Lazy load workload data if not in memory
                if not self.dbms.in_memory:
                    result["load_info"] = self._do_load(self.db_data_dirpath)
                else:
                    result["load_info"] = "N/A"
            else:
                result["load_info"] = "N/A"
        except Exception as err:
            result["load_info"] = ""
            result.update(report_and_return_error(self.logger, err, "load-failed"))

            # erase loaded data that are potentially invalid/incomplete
            evict_result = self.db_storage_manager.evict_entry(
                dbms_info, benchmark_info
            )
            if evict_result:
                self.logger.error("Could not evict entry which timed-out.. :(")

        # Load finished -- return result
        return result

    def run(
        self,
        dbms_info_dict: dict,
        benchmark_info_dict: dict,
        samplers_info: dict | None = None,
        _debug=False,
        _stop=True,
    ) -> dict:
        """Evaluate a DBMS configuration on the given benchmark"""

        result = self.load(dbms_info_dict, benchmark_info_dict, samplers_info, _debug)

        # if the load succeeded
        print(result)
        if "load_info" not in result or result["load_info"] != "":
            try:
                # Run workload
                if self.dbms.in_memory:
                    result.update(self._do_inmem_fused_load_run())
                else:
                    result.update(self._do_run(self.db_data_dirpath))
            except Exception as err:
                result.update(report_and_return_error(self.logger, err, "run-failed"))

        # Try to get dbms log
        try:
            cp = subprocess.run(
                "docker logs dbms", shell=True, encoding="utf-8", capture_output=True
            )
            stdout, stderr = cp.stdout, cp.stderr
        except Exception as err:
            self.logger.debug(f"Could not get dbms logs: {repr(err)}")
            stdout, stderr = "", ""

        dbms_log = {"stdout": stdout, "stderr": stderr}
        for ss, v in dbms_log.items():
            dbms_log[ss] = trim_stream_output(v, stream_name=ss)
        result["dbms_log"] = dbms_log

        try:
            shutil.copytree(local_db_disk_dirpath / "log", "/log", dirs_exist_ok=True)
        except:
            pass

        if _stop:
            # Stop dbms container
            try:
                self.dbms.stop()
            except Exception as err:
                result.update(
                    report_and_return_error(self.logger, err, "stop-dbms-failed")
                )

            # Delete data from disk
            local_db_disk_dirpath = config.disk_mount_point.local / self.dbms.name

            try:
                erase_dir(
                    local_db_disk_dirpath.resolve().as_posix(), ignore_errors=False
                )
            except FileNotFoundError:
                pass
            finally:
                disk_sync()

        result["end"] = datetime.now().isoformat()

        if _debug:
            import yaml

            def get_dict_types(d):
                r = {}
                for k, v in d.items():
                    if isinstance(v, dict):
                        r[k] = get_dict_types(v)
                    else:
                        r[k] = repr(type(v))
                return r

            result_types = get_dict_types(result)
            self.logger.info(f"Returning result:\n{yaml.dump(result_types)}")

            self.logger.info("Approximate results field size report:")
            output = "\n"
            for k, v in result.items():
                output += f"\t{k}: {asizeof.asized(v).size / (2 ** 20) : .2f} MB\n"
            self.logger.info(output)

        # Run finished -- return result
        return result

    def cleanup(self):
        """Cleanup directories"""
        config.cleanup_local_dirs()

        self.logger.info("Cleanup finished! :)")

    def _do_load(self, dst_db_data_dirpath: PathPair) -> dict:
        """Launch dbms container and populate it with data

        NOTE: Data is stored at the disk backup mount point
        """
        start = datetime.now()

        # Write load configuration to file
        # NOTE: `host_db_conf_filepath' is the path outside the docker container
        self.logger.info("Writing load configuration to file...")
        _, db_conf_filename = self.dbms.write_config_file(
            config.workspace_dir.local, DBMSConfigType.LOAD
        )
        host_db_conf_filepath = (
            config.workspace_dir.host / db_conf_filename
        ).as_posix()
        self.logger.info(f"DBMS Configuration filepath (host): {host_db_conf_filepath}")

        extra_env_vars = {
            "DB_CONF_FILEPATH": host_db_conf_filepath,
            # override compose.yaml's disk mount point
            "DISK_MOUNT_POINT": dst_db_data_dirpath.host,
            "CPUSET_CPUS_WORKLOAD": f"{os.environ['CPUSET_CPUS_WORKLOAD']},{os.environ['CPUSET_CPUS_DRIVER']}",  # Speed-up loading by using all available hw cores
        }

        # Launch dbms
        env = {**os.environ.copy(), **extra_env_vars}
        self.dbms.start(env=env)

        # Wait until dbms has been launched
        if not self.dbms.wait_until_connected(extra_wait=10):
            error = "[load] Cannot connect to DBMS :("
            self.logger.warn(error)
            raise RuntimeError(error)

        # Init database
        self.dbms.init()

        load_info = self.benchmark.load()
        self.logger.debug(f"Loading log: {load_info}")

        # Get database size
        load_info["db_size_gib"] = self.dbms.get_database_size_gib()
        self.logger.info(f'Database Size: {load_info["db_size_gib"]:.3f} GiB')

        # Stop dbms container
        self.dbms.stop()

        elapsed_seconds = (datetime.now() - start).total_seconds()
        self.logger.info(f"Loading data to DBMS took {elapsed_seconds:.2f} seconds")
        return load_info

    def _do_run(self, src_db_data_dirpath: PathPair) -> dict:
        # Init entry to be populated later
        entry = {}

        # Generate and write configuration to conf run file
        entry["conf_file"], db_conf_filename = self.dbms.write_config_file(
            config.workspace_dir.local, DBMSConfigType.RUN
        )
        host_db_conf_filepath = (
            config.workspace_dir.host / db_conf_filename
        ).as_posix()

        ## Copy loaded data from backup mount point to disk mount point
        start = datetime.now()

        # Clear leftovers from previous runs
        local_db_disk_dirpath = config.disk_mount_point.local / self.dbms.name
        self.logger.info(
            f"Clearing leftovers from previous runs: {local_db_disk_dirpath}"
        )
        try:
            erase_dir(local_db_disk_dirpath.resolve().as_posix(), ignore_errors=False)
        except FileNotFoundError:
            self.logger.info(f"No leftovers found at {local_db_disk_dirpath}")

        # Copy data from backup to disk mount point
        self.logger.info(
            f"Copying DBMS data from backup [{src_db_data_dirpath.local}] "
            f"to target [{config.disk_mount_point.local.as_posix()}]..."
        )
        shutil.copytree(
            src_db_data_dirpath.local, config.disk_mount_point.local, dirs_exist_ok=True
        )
        disk_sync()

        elapsed_seconds = (datetime.now() - start).total_seconds()
        self.logger.info(f"Copying DBMS data took {elapsed_seconds:.2f} seconds")

        # Prepare env-vars
        host_disk_mount_point = config.disk_mount_point.host.as_posix()
        extra_env_vars = {
            "DB_CONF_FILEPATH": host_db_conf_filepath,
            "DISK_MOUNT_POINT": host_disk_mount_point,
        }
        env = {**os.environ.copy(), **extra_env_vars}

        ## Launch dbms container
        self.dbms.start(env=env)

        # Check that it has loaded successfully
        if not self.dbms.wait_until_connected(extra_wait=10):
            error = (
                "[run] Cannot connect to database :( -> "
                "Possible reason: invalid configuration file"
            )
            self.logger.warn(error)
            raise RuntimeError(error)

        # trim ssd // todo add check
        # TODO: handle this one
        # self.logger.info('Trimming SSD...')
        # run_command('echo "sudo fstrim -a -v" > /nautilus-host/host-push', check=True)
        # run_command('cat /nautilus-host/host-pull', check=True)

        # Clear caches before run
        clear_system_caches(level=3)

        entry["run_info"] = {}
        raised = False

        # Init samplers
        self.samplers.setup()

        # Launch warm-up round
        warmup_round_info = {}
        try:
            warmup_round_info = self.benchmark.run(BenchmarkRound.WARMUP)
        except Exception as err:
            self.logger.exception(err)
            self.logger.error("While running warmup round :(")
            warmup_round_info["result"] = f"ERROR: {repr(err)}"
            raised = True
        finally:
            entry["run_info"][BenchmarkRound.WARMUP.value] = warmup_round_info
            if raised:
                return entry  # early exit

        # Start samplers
        self.samplers.start()

        # Launch benchmark round
        benchmark_round_info = {}
        try:
            benchmark_round_info = self.benchmark.run(BenchmarkRound.BENCHMARK)
        except Exception as err:
            self.logger.exception(err)
            self.logger.error("While running BENCHMARK round :(")
            benchmark_round_info["result"] = f"ERROR: {repr(err)}"
            raised = True
        finally:
            entry["run_info"][BenchmarkRound.BENCHMARK.value] = benchmark_round_info
            # Stop samplers
            self.samplers.stop()

            if raised:
                return entry

        # Get metrics
        metrics = {}

        # Metrics from samplers
        metrics["samplers"] = self.samplers.get_results()

        # Store performance statistics
        if not raised:
            metrics["performance_stats"] = self.benchmark.perf_stats
            entry.update(metrics)  # Update entry

        # Get database size
        metrics["db_size_gib"] = self.dbms.get_database_size_gib()
        self.logger.info(f'Database Size: {metrics["db_size_gib"]:.3f} GiB')

        return entry

    def _do_inmem_fused_load_run(self) -> dict:
        entry = {}
        entry["conf_file"], db_conf_filename = self.dbms.write_config_file(
            config.workspace_dir.local, DBMSConfigType.RUN
        )
        host_db_conf_filepath = (
            config.workspace_dir.host / db_conf_filename
        ).as_posix()

        self.logger.info(f"DBMS Configuration filepath (host): {host_db_conf_filepath}")

        # Prepare env-vars
        host_disk_mount_point = config.disk_mount_point.host.as_posix()
        extra_env_vars = {
            "DB_CONF_FILEPATH": host_db_conf_filepath,
            "DISK_MOUNT_POINT": host_disk_mount_point,
        }
        env = {**os.environ.copy(), **extra_env_vars}

        ## Launch dbms container
        self.dbms.start(env=env)

        # Wait until dbms has been launched
        if not self.dbms.wait_until_connected(extra_wait=30):
            error = "[load] Cannot connect to DBMS :("
            self.logger.warn(error)
            raise RuntimeError(error)

        # Init database
        self.dbms.init()

        load_info = self.benchmark.load()
        self.logger.debug(f"Loading log: {load_info}")

        # Clear caches before run
        clear_system_caches(level=3)

        entry["run_info"] = {}
        raised = False

        # Init samplers
        self.samplers.setup()

        # Launch warm-up round
        warmup_round_info = {}
        try:
            warmup_round_info = self.benchmark.run(BenchmarkRound.WARMUP)
        except Exception as err:
            self.logger.exception(err)
            self.logger.error("While running warmup round :(")
            warmup_round_info["result"] = f"ERROR: {repr(err)}"
            raised = True
        finally:
            entry["run_info"][BenchmarkRound.WARMUP.value] = warmup_round_info
            if raised:
                return entry  # early exit

        # Start samplers
        self.samplers.start()

        # Launch benchmark round
        benchmark_round_info = {}
        try:
            benchmark_round_info = self.benchmark.run(BenchmarkRound.BENCHMARK)
        except Exception as err:
            self.logger.exception(err)
            self.logger.error("While running BENCHMARK round :(")
            benchmark_round_info["result"] = f"ERROR: {repr(err)}"
            raised = True
        finally:
            entry["run_info"][BenchmarkRound.BENCHMARK.value] = benchmark_round_info
            # Stop samplers
            self.samplers.stop()

            if raised:
                return entry

        # Get metrics
        metrics = {}

        # Metrics from samplers
        metrics["samplers"] = self.samplers.get_results()

        # Store performance statistics
        if not raised:
            metrics["performance_stats"] = self.benchmark.perf_stats
            entry.update(metrics)  # Update entry

        # Get database size
        metrics["db_size_gib"] = self.dbms.get_database_size_gib()
        self.logger.info(f'Database Size: {metrics["db_size_gib"]:.3f} GiB')

        return entry
