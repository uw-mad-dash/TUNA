import logging

from nautilus.dbms import DBMS, DBMSInfo
from nautilus.utils import run_command

class Cassandra(DBMS):
    name = 'cassandra'
    port = 9042
    in_memory = False

    CONF_FILENAME_EXT = '.yaml'
    init_db_filepath = '/tmp/init-db/init.cql'

    def __init__(self, config: dict[str, str], info: DBMSInfo) -> None:
        self.logger = logging.getLogger(self._logger_name)
        self.logger.info(f'Cassandra version: {info.version}')

        # TODO: Add support for version
        # TODO: check with supported versions

        super().__init__(config, info)

    def init(self):
        # Execute the init.sql script only if it exists
        cmd = (f'docker exec {self.host} bash -c '
            f'"if [ -e {self.init_db_filepath} ]; then cqlsh -f {self.init_db_filepath}; fi"')
        return run_command(cmd) == 0

    def _generate_conf_file(self):

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
                l.rstrip() for l in f.read().split('\n') ]

        if (self.db_config is None) or (self.db_config == { }):
            self.logger.info('Got empty/null configuration. Returning default!')
            return '\n'.join(default_conf_lines)

        # Construct substitution lines
        subs_conf_lines = {
            k: f'{k}: {_to_valid_value(v)}' for k, v in self.db_config.items() }

        # Iterate over configuration lines and replace lines
        run_conf_lines = [ ]
        for i, l in enumerate(default_conf_lines):
            found, run_line = False, l
            remove_keys = [ ]

            # Search through new conf lines to see if we need to replace line
            for k, subs_line in subs_conf_lines.items():
                if not l.startswith(f'{k}:') and not l.startswith(f'# {k}:'):
                    continue

                if found:
                    self.logger.warn(f'More than one line match! [`{k}`]')

                found, run_line = True, subs_line
                remove_keys.append(k)

                self.logger.debug(f'Replacing line {i}: `{l}` with `{subs_line}`')

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
