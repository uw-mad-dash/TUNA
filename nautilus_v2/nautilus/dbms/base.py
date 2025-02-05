import logging
import socket
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from functools import cached_property
from pathlib import Path
from time import sleep

from dacite import from_dict as dataclass_from_dict, DaciteError
from docker import from_env

from nautilus.dbms.utils import apply_jaydebeapi_patch
from nautilus.utils import run_command

import jaydebeapi

apply_jaydebeapi_patch()


@dataclass(frozen=True)
class DBMSInfo:
    name: str
    # (knob, value) configuration dictionary
    config: (
        dict[str, int | float | str] | None
    )  # pylint: disable=unsubscriptable-object
    version: str | None


class DBMSConfigType(Enum):
    """Enum for configuration types"""

    LOAD = "load"
    RUN = "run"


class DBMS(ABC):
    """Base class for all DBMS classes."""

    host: str = "dbms"

    port: int
    name: str
    in_memory: bool

    driver_jar_filename: str = None

    # Required fields
    CONF_FILENAME_EXT: str  # must be defined by subclass
    CONF_DEFAULT_FILE_STEM = "config-default"
    CONF_LOAD_FILE_STEM = "config-load"
    CONF_RUN_FILE_STEM = "config-run"

    # Fields initialized by subclass
    conf_default_filepath: Path
    conf_load_filepath: Path
    conf_run_filepath: Path

    logger: logging.Logger
    _logger_name = ".".join(__name__.split(".")[:-1])  # hide .base

    def __init__(self, config: dict[str, str], info: DBMSInfo):
        self.info = info

        # TODO: make this a dataclass
        self.db_name = config["db_name"]
        self.user = config["user"]
        self.password = config["password"]
        self.root_password = config["root_password"]
        self.docker_container_name = config["docker_container_name"]

        # Validate that host:port are defined
        if not hasattr(self, "port"):
            raise RuntimeError("DBMS port *not* defined")
        if not hasattr(self, "host"):
            raise RuntimeError("DBMS host *not* defined")

        # Validate that config filenames suffix has been defined
        if not hasattr(self, "CONF_FILENAME_EXT"):
            raise RuntimeError("DBMS config filename extension NOT defined")
        if not hasattr(self, "driver_jar_properties"):
            raise RuntimeError("DBMS `driver_jar_properties' dict NOT defined")

        # Dictionary of key-value pairs for DBMS configuration
        self.db_config = info.config

    def start(self, env=None):
        env = env or {}
        if "DBMS_VERSION" not in env:
            env["DBMS_VERSION"] = self.version  # set DBMS version

        self.logger.info("Starting DBMS container...")
        cmd = (
            f"docker compose -f {self.dockerfile_filepath} config && "
            f"docker compose -f {self.dockerfile_filepath} up -d --force-recreate"
        )
        run_command(cmd, env=env, check=True)
        self.logger.info("Started!")

    def stop(self, raise_if_not_found=True):
        """Stops the DBMS container (if exists)"""
        client = from_env()

        self.logger.info("Stopping DBMS container...")
        try:
            dbms_container = client.containers.get(self.docker_container_name)
            dbms_container.stop(timeout=1)
        except Exception as err:
            if raise_if_not_found:
                self.logger.error(f"Failed to stop DBMS container: {repr(err)}")
                raise err
        else:
            self.logger.info("Stopped!")
        finally:
            del client

    def create_connection(self) -> jaydebeapi.Connection:
        """Create a connection to the DBMS using JDBC"""
        driver_name = self.driver_jar_properties["name"]
        subprotocol = self.driver_jar_properties["subprotocol"]

        conn_url = f"jdbc:{subprotocol}://{self.host}:{self.port}/{self.db_name}"
        self.logger.debug(f"Connecting to: {conn_url}")

        conn = jaydebeapi.connect(
            driver_name,
            conn_url,
            [self.user, self.password],
            self.driver_jar_filepath.as_posix(),
        )

        return conn

    def is_connected(self, warn_if_error=False) -> bool:
        """Checks if DBMS socket is open for connections

        Not sure if we need dedicated dbms client libraries
        for more robustness though.

        TODO: Use JDBC driver to test actually connection
        """

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.logger.debug(f"Try to connect to dbms [{self.host}:{self.port}]")
        try:
            s.connect((self.host, self.port))
            s.shutdown(socket.SHUT_RDWR)
        except Exception as err:
            log_level = logging.WARNING if warn_if_error else logging.DEBUG
            self.logger.log(log_level, f"Failed to connect... Reason [`{err}`]")
            return False

        self.logger.info("Connected!")
        return True

    def wait_until_connected(self, timeout=120, sleep_secs=3, extra_wait=3) -> bool:
        """Blocks until connected to DBMS or timed out"""
        start = datetime.now()
        num_attempts = 0

        while (datetime.now() - start).total_seconds() < timeout:
            self.logger.debug("Trying to connect to dbms...")
            num_attempts += 1

            if self.is_connected(warn_if_error=num_attempts >= 10):
                self.logger.info("Connected! :)")
                # Conservative wait
                self.logger.debug(f"Waiting {extra_wait} extra secs...")
                sleep(extra_wait)
                return True

            sleep(sleep_secs)

        return False

    def write_config_file(
        self, directory: Path, type: DBMSConfigType
    ) -> tuple[str, Path]:
        """Write the DBMS configuration to the specified file and
        return the file contents and the filename.
        """

        if type == DBMSConfigType.LOAD:
            # Read load config from file (local path)
            filepath = self.conf_load_filepath
            with open(self.conf_load_filepath, "r") as f:
                conf_file_contents = f.read()

        elif type == DBMSConfigType.RUN:
            # Generate run config file from user-provided config
            filepath = self.conf_run_filepath
            conf_file_contents = self._generate_conf_file()
            if conf_file_contents is None or len(conf_file_contents) == 0:
                error = "Empty generated configuration file :("
                self.logger.error(error)
                raise RuntimeError(error)

        # Write the configuration file to the specified directory
        # using the same filename as the original file
        db_conf_filename = filepath.relative_to(self.conf_dir)

        filepath = directory / db_conf_filename
        with open(filepath, "w") as f:
            f.write(conf_file_contents)
            self.logger.info(f"Configuration file written to: {filepath}")

        return conf_file_contents, db_conf_filename

    def modify_db_config(self, custom_config, override=False):
        """Add more custom knob values to existing user-defined db configuration
        NOTE: if a custom value for a knob exists, action depends on `override`
        """
        if self.db_config is None:
            self.db_config = {}

        for (
            knob,
            value,
        ) in custom_config.items():
            if knob in self.db_config and not override:
                # keep user-specified knob value
                self.logger.debug(
                    f'Knob "{knob}" (with value "{self.db_config[knob]}") '
                    "exists in user-provided config. Keeping this value."
                )
                continue

            self.logger.debug(f"Modifying knob value: '{knob}' = '{value}'")
            self.db_config[knob] = value

        self.logger.info(f"New DB config (after modification): {self.db_config}")

    @abstractmethod
    def init(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def run_command(self, command: str, params: list | None = None) -> list:
        raise NotImplementedError

    @abstractmethod
    def get_database_size_gib(self, rounded=True) -> float:
        raise NotImplementedError

    @abstractmethod
    def _generate_conf_file(self) -> str:
        raise NotImplementedError

    def __str__(self):
        return f"DBMS class instance ({self.name})"

    @cached_property
    def dockerfile_filepath(self) -> Path:
        """Retrieve DBMS docker compose file

        NOTE: Suffix of the docker compose file can be either 'yml' or 'yaml'
        """
        filepath = (self.conf_dir / "docker-compose.yml").resolve()
        if not filepath.exists():
            filepath = (self.conf_dir / "docker-compose.yaml").resolve()
            if not filepath.exists():
                raise FileNotFoundError(
                    f"DBMS docker compose file not found @[{filepath}]"
                )

        return filepath

    @cached_property
    def driver_jar_filepath(self) -> Path:
        """Retrieve the DBMS driver java class filepath"""
        if self.driver_jar_filename is None:
            return None

        filepath = (self.conf_dir / self.driver_jar_filename).resolve()
        if not filepath.exists():
            raise FileNotFoundError(
                f"DBMS driver jar filepath does not exist [@{filepath}]"
            )

        return filepath

    @cached_property
    def conf_dir(self) -> Path:
        """Retrieve DBMS configuration directory"""
        dirpath = (self.dirpath / self.name).resolve()
        if not dirpath.exists():
            raise FileNotFoundError(f"DBMS config dir does not exist [@{dirpath}]")

        self.logger.info(f"DBMS conf directory: {dirpath}")
        return dirpath

    @cached_property
    def dirpath(self) -> Path:
        """Retrieve DBMS directory"""
        return Path(__file__).parent

    @classmethod
    def from_info(cls, config, info) -> "DBMS":
        # `info' is a dict
        cls, info = cls._get_cls(info)
        return cls(config, info)

    @staticmethod
    def _get_cls(info):
        name = info["name"]

        from nautilus.dbms.cassandra import Cassandra
        from nautilus.dbms.mysql import MySQL
        from nautilus.dbms.nginx import Nginx
        from nautilus.dbms.postgres import PostgreSQL
        from nautilus.dbms.redis import Redis

        AVAILABLE_DBMS = {
            "cassandra": (Cassandra, DBMSInfo),
            "mysql": (MySQL, DBMSInfo),
            "nginx": (Nginx, DBMSInfo),
            "redis": (Redis, DBMSInfo),
            "postgres": (PostgreSQL, DBMSInfo),
        }

        try:
            cls, info_cls = AVAILABLE_DBMS[name]
        except KeyError:
            error_msg = f"ERROR: DBMS `{name}`] not found :("
            print(error_msg)
            raise ValueError(error_msg)

        try:
            dc = dataclass_from_dict(data_class=info_cls, data=info)
        except DaciteError as err:
            print(f"ERROR: While creating dataclass from dict: {repr(err)}")
            raise err

        return cls, dc
