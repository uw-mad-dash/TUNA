import logging
from fnmatch import fnmatch
import jaydebeapi
from jaydebeapi import _DEFAULT_CONVERTERS, _java_to_py
import json

from nautilus.dbms import DBMS, DBMSInfo
from nautilus.benchmarks.common import IsolationLevel

_DEFAULT_CONVERTERS.update({'BIGINT': _java_to_py('longValue')})
_DEFAULT_CONVERTERS.update({'VARCHAR': _java_to_py('toString')})

class PostgreSQL(DBMS):
    name = 'postgres'
    port = 5432
    in_memory = False

    driver_jar_filename = 'postgresql-42.7.1.jar'
    driver_jar_properties = {
        'name': 'org.postgresql.Driver',
        'subprotocol': 'postgresql',
        'isolation_level': IsolationLevel.TRANSACTION_READ_COMMITTED,
        'url_suffix': '?sslmode=disable&amp;reWriteBatchedInserts=true',
    }

    CONF_FILENAME_EXT = 'conf'

    DEFAULT_VERSION = '16.1'
    SUPPORTED_VERSIONS = [
        '9.6', '13.*', '14.*', '15.*', '16.*',
    ]

    def __init__(self, config: dict[str, str], info: DBMSInfo) -> None:
        self.logger = logging.getLogger(self._logger_name)
        self.logger.info(f'PostgreSQL version: {info.version}')

        version = info.version
        if version is None:
            self.logger.info('No PostgreSQL version provided -- '
                        f'falling back to default [{self.DEFAULT_VERSION}]')
            version = self.DEFAULT_VERSION

        # Check if version is supported
        if not any(fnmatch(version, sv) for sv in self.SUPPORTED_VERSIONS):
            error_msg = (f'PostgreSQL version {version} not supported :('
                         f'Supported versions: {self.SUPPORTED_VERSIONS}')
            self.logger.error(error_msg)
            raise ValueError(error_msg)

        self.version = version

        ## Construct file paths of PostgreSQL configurations
        self.major_version = int(version.split('.')[0])

        # Default
        filename = f'{self.CONF_DEFAULT_FILE_STEM}.{self.major_version}.{self.CONF_FILENAME_EXT}'
        self.conf_default_filepath = self.conf_dir / filename
        if not self.conf_default_filepath.exists() or not self.conf_default_filepath.is_file():
            error = f'PostgreSQL default config [version={self.major_version}] not found: {self.conf_default_filepath}'
            self.logger.error(error)
            raise FileNotFoundError(error)

        self.logger.debug(f'{self.conf_default_filepath = }')

        # Load
        try:
            filename = f'{self.CONF_LOAD_FILE_STEM}.{self.major_version}.{self.CONF_FILENAME_EXT}'
            filepath = self.conf_dir / filename
            assert filepath.exists() and filepath.is_file()
        except AssertionError:
            filename = f'{self.CONF_LOAD_FILE_STEM}.{self.CONF_FILENAME_EXT}'
            filepath = self.conf_dir / filename
            assert filepath.exists() and filepath.is_file(), \
                    f'Cross-version config load file not found: {self.conf_load_filepath}'
            self.logger.info('Did not find version-specific load config; using cross-version one')

        self.conf_load_filepath = filepath
        self.logger.info(f'Load config: {self.conf_load_filepath.as_posix() = }')

        # Run -- this file will be created
        filename = f'{self.CONF_RUN_FILE_STEM}.{self.version}.{self.CONF_FILENAME_EXT}'
        self.conf_run_filepath = self.conf_dir / filename
        self.logger.info(f'Run config: {self.conf_run_filepath.as_posix() = }')

        super().__init__(config, info)

    def init(self) -> None:
        """ Database init is done implicitly from within docker container """
        pass

    def get_database_size_gib(self, rounded=True) -> float:
        """ Get the size of the database """
        try:
            db_size = self.run_command(f"SELECT pg_database_size('{self.db_name}')")[0]
        except Exception as err:
            self.logger.error(f'While retrieving db size: {repr(err)}')
            db_size = float('nan')

        # Convert to GiB
        db_size /= (2 ** 30)
        return round(db_size, 3) if rounded else db_size

    def run_command(self, command: str, params: list | None = None) -> list:
        """ Run query on database """
        try:
            conn: jaydebeapi.Connection = self.create_connection()
        except Exception as err:
            self.logger.error(f'While attempting to connect to DBMS: {repr(err)}')
            return float('nan')
        finally:
            curs: jaydebeapi.Cursor = conn.cursor()
        
        try:
            self.logger.info(command)
            self.logger.info(params)
            curs.execute(command, params)
            result = curs.fetchall()[0]
            
            def format(item):
                if "getValue" in dir(item):
                    return item.getValue()
                return item
            result = tuple([format(item) for item in result])
            self.logger.info(result)
            return result
        finally:
            curs.close()
            conn.close()

    def _generate_conf_file(self) -> str:
        """ Generate a configuration file for PostgreSQL

        The configuration file is generated by replacing the knob values
        in the default configuration file with the user-provided values.
        """

        def _to_valid_value(v):
            if isinstance(v, (str, int, bool)):
                return str(v)
            elif isinstance(v, float):
                return '{0:.2f}'.format(v)
            else:
                error = f'Unexpected type: {type(v)}'
                self.logger.error(error)
                raise RuntimeError(error)

        # Read default configuration
        with open(self.conf_default_filepath, 'r') as f:
            default_conf_lines = [
                lst.rstrip() for lst in f.read().split('\n') ]

        if (self.db_config is None) or (self.db_config == { }):
            # Return default configuration
            self.logger.info('Got empty/null configuration. Returning default!')
            return '\n'.join(default_conf_lines)

        # Construct substitution lines
        subs_conf_lines = {
            k: f'{k} = {_to_valid_value(v)}' for k, v in self.db_config.items() }

        # Iterate over configuration lines and replace lines
        run_conf_lines = [ ]
        for i, line in enumerate(default_conf_lines):
            found, run_line = False, line
            remove_keys = [ ]

            # Search through new conf lines to see if we need to replace line
            for k, subs_line in subs_conf_lines.items():
                if not line.startswith(f'#{k} ='):
                    continue

                if found:
                    self.logger.warn(f'More than one line match! [`{k}`]')

                found, run_line = True, subs_line
                remove_keys.append(k)

                self.logger.debug(f'Replacing line {i}: `{line}` with `{subs_line}`')

            # Append line to new configuration
            run_conf_lines.append(run_line)
            for k in remove_keys:
                del subs_conf_lines[k]

        if len(subs_conf_lines) > 0:
            error = 'Could not find & replace all knobs. ' \
                    f'Missing: [{", ".join(subs_conf_lines.keys())}]'
            self.logger.error(error)
            raise RuntimeError(error)

        # Return new configuration
        return '\n'.join(run_conf_lines)
