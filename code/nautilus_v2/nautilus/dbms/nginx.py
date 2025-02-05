import logging
from fnmatch import fnmatch
import os

from nautilus.benchmarks.common import IsolationLevel
from nautilus.dbms import DBMS, DBMSInfo
from nautilus.utils import run_command


class Nginx(DBMS):
    name: str = "nginx"
    port: int = 80
    in_memory: bool = True

    CONF_FILENAME_EXT: str = "conf"
    init_db_filepath: str = ""
    driver_jar_properties: dict = {}  # Required but not used

    DEFAULT_VERSION: str = "1.27"
    SUPPORTED_VERSIONS: list[str] = ["1.27"]

    def __init__(self, config: dict[str, str], info: DBMSInfo) -> None:
        self.logger = logging.getLogger(self._logger_name)
        self.logger.info(f"nginx version: {info.version}")

        version = info.version
        if not version:
            self.logger.info(
                "No nginx version provided -- "
                f"falling back to default [{self.DEFAULT_VERSION}]"
            )
            version = self.DEFAULT_VERSION

        # Check if version is supported
        if not any(fnmatch(version, sv) for sv in self.SUPPORTED_VERSIONS):
            error_msg = (
                f"nginx version {version} not supported :("
                f"Supported versions: {self.SUPPORTED_VERSIONS}"
            )
            self.logger.error(error_msg)
            raise ValueError(error_msg)

        self.version = version

        ## Construct file paths of Redis configurations
        # Default
        filepath = (
            self.conf_dir / f"{self.CONF_DEFAULT_FILE_STEM}.{self.CONF_FILENAME_EXT}"
        )
        self.logger.debug(f"{filepath = }")

        if not filepath.exists() or not filepath.is_file():
            error = f"nginx default config not found: {self.conf_default_filepath}"
            self.logger.error(error)
            raise FileNotFoundError(error)

        self.conf_default_filepath = filepath

        # Load
        filepath = (
            self.conf_dir / f"{self.CONF_LOAD_FILE_STEM}.{self.CONF_FILENAME_EXT}"
        )
        assert (
            filepath.exists() and filepath.is_file()
        ), f"Cross-version config load file not found: {self.conf_load_filepath}"
        self.conf_load_filepath = filepath
        self.logger.info(f"Load config: {self.conf_load_filepath = }")

        # Run -- this file will be created
        major_version = ".".join(version.split(".")[:2])  # e.g. 8.0.23 -> 8.0
        filepath = (
            self.conf_dir
            / f"{self.CONF_RUN_FILE_STEM}.{major_version}.{self.CONF_FILENAME_EXT}"
        )
        self.conf_run_filepath = self.conf_dir / filepath
        self.logger.info(f"Run config: {self.conf_run_filepath = }")

        super().__init__(config, info)

    def init(self) -> None:
        """nginx init is done implicitly from within docker container"""
        pass

    def get_database_size_gib(self, rounded=True) -> float:
        """Retrieve the size of the database in GiB"""
        return -1

    def run_command(self, command: str, params: list | None = None) -> list:
        """Run query on database"""
        raise NotImplementedError

    def _generate_conf_file(self):
        """Generate nginx configuration file

        generates the nginx configuration file based on the values in db_config
        """

        # Read default configuration
        with open(self.conf_default_filepath, "r") as f:
            default_conf = f.read()

        if (self.db_config is None) or (self.db_config == {}):
            # Return default configuration
            self.logger.info("Got empty/null configuration. Returning default!")
            return default_conf

        # generate the knobs to add
        to_add = "\n"
        for k, v in self.db_config.items():
            to_add += f"{k} {v};\n"

        # insert the knobs into the default configuration at the template location
        conf = default_conf.replace("### replace", to_add)
        return conf
