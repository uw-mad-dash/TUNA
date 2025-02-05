import itertools
import logging
from datetime import datetime

from nautilus.dbms.postgres import PostgreSQL
from nautilus.samplers import SamplerInterface

class PostgreSQLMetricsSampler(SamplerInterface):
    """ Sampler for PostgreSQL metrics.

    This sampler collects metrics from useful views in the `pg_catalog` schema.
    """

    GLOBAL_STAT_VIEWS = [
        'pg_stat_archiver',
        'pg_stat_bgwriter',
    ]
    PER_DB_STAT_VIEWS = [
        'pg_stat_database',
        'pg_stat_database_conflicts',
    ]
    PER_TABLE_STAT_VIEWS = [
        'pg_stat_user_tables',
        'pg_stat_user_indexes',
        'pg_statio_user_tables',
        'pg_statio_user_indexes',
    ]
    TABLE_NAME_COLUMN = 'relname'

    def __init__(
        self,
        name: str,
        dbms: PostgreSQL,
        interval: int = 5,
        query_timeout_ms: int = 1000,
        #reset_metrics: bool = False,
        per_table_metrics: bool = False,
    ) -> None:
        self.logger = logging.getLogger(__name__)
        self.logger.info(f'PostgreSQL metrics sampler [name={name}]')

        self.database_name = dbms.db_name
        self.create_connection_func = dbms.create_connection
        self.dbms_major_version = dbms.major_version

        self.query_timeout_ms = query_timeout_ms
        #self.reset_metrics = reset_metrics
        self.per_table_metrics = per_table_metrics
        super().__init__(name, interval=interval)

        # Set views -- optionally include per-table metrics
        self._set_views()

    def setup(self):
        super().setup()

        self.samples = {
            v: [ ] for v in itertools.chain(*self.views) }
        self.timestamps = [ ]
        self.conn = self.create_connection_func()
        self.curs = self.conn.cursor()

        # Reset metrics
        #if self.reset_metrics:
            # cluster-wide
            #for v in self.GLOBAL_STAT_VIEWS:
            #    assert v.startswith('pg_stat_'), f'Unexpected view name: {v}'
            #    v = v[len('pg_stat_') :]
            #    self.curs.execute(f"SELECT pg_stat_reset_shared('{v}');")

            # NOTE: we do not reset per-database stats because it would interfere with
            # autovacuum and other background processes that rely on them to work properly
            # TODO: perform diff on resulting stats
            #self.curs.execute('SELECT pg_stat_reset();')

        # Set query timeout
        self.curs.execute(f'SET statement_timeout TO {self.query_timeout_ms}')

        if self.per_table_metrics:
            # Store column names of tables
            self.views_cols = self._get_views_cols()
            #
            self.table_name_idx = { }
            for v in self.PER_TABLE_STAT_VIEWS:
                try:
                    self.table_name_idx[v] = \
                        self.views_cols[v].index(self.TABLE_NAME_COLUMN)
                except ValueError:
                    raise RuntimeError('Table name column not found :(')

    def teardown(self):
        """ Close JDBC connection and cursor """
        super().teardown()
        self.curs.close()
        self.conn.close()

    def sample(self):
        """ Performs a sampling """
        def get_column_names(curs):
            return [d[0] for d in curs.description]
        def get_column_types(curs):
            return [d[1] for d in curs.description]

        def get_global_stats(view):
            """ Get stats from 'global' views
            One or more rows are returned
            """
            self.curs.execute(f"select * from {view}")
            rows = self.curs.fetchall()
            if len(rows) == 0:
                self.logger.warning(f"Expected 1+ rows from `{view}' but got zero")
            column_names = get_column_names(self.curs)

            #self.logger.info(dict(zip(column_names, get_column_types(self.curs))))
            #self.logger.info([ (rows[0][i], type(rows[0][i])) for i in range(len(rows[0]))] )
            return [ dict(zip(column_names, row)) for row in rows ] or None

        def get_per_database_stats(view: str):
            """ Get stats from 'per-database' views
            Filter results by current db name ; only one row is returned
            """
            self.curs.execute(
                f"select * from {view} where datname='{self.database_name}'")
            rows = self.curs.fetchall()
            if len(rows) != 1:
                self.logger.warning(f"Expected 1 row from `{view}' but got {len(rows)}")
            column_names = get_column_names(self.curs)

            row = rows[0] if len(rows) > 0 else []

            #self.logger.info(dict(zip(column_names, get_column_types(self.curs))))
            #self.logger.info([ (row[i], type(row[i])) for i in range(len(row))] )
            return dict(zip(column_names, row)) if row is not None else None

        def get_per_table_stats(view):
            """ Get stats from 'per-table' views
            Typically many rows are returned ; one for each table/index
            """
            self.curs.execute(f'select * from {view}')
            rows = self.curs.fetchall()
            if self.curs.rowcount == 0:
                self.logger.warning(f"Expected 1+ rows from `{view}' but got zero")
            column_names = get_column_names(self.curs)

            #self.logger.info(dict(zip(column_names, get_column_types(self.curs))))
            #self.logger.info([ (rows[0][i], type(rows[0][i])) for i in range(len(rows[0]))] )
            return [ dict(zip(column_names, row)) for row in rows ] or None

            #idx = self.table_name_idx[view]
            #return { row[idx]: row for row in rows }

        functions = [
            get_global_stats,
            get_per_database_stats,
        ]
        if self.per_table_metrics:
            functions.append(get_per_table_stats)

        for f, v in zip(functions, self.views):
            for t in v:
                try:
                    value = f(t)
                except Exception as err:
                    self.logger.error(f"While sampling `{t}': {repr(err)}")
                    value = None
                finally:
                    self.samples[t].append(value)

        self.timestamps.append(datetime.now())

    def _set_views(self):
        """ Set PG views to be used for sampling

        Source: https://pgpedia.info/version-charts/system-statistics-views.html
        """
        # GLOBAL_STAT_VIEWS
        if self.dbms_major_version >= 13:
            self.GLOBAL_STAT_VIEWS.append('pg_stat_slru')
        if self.dbms_major_version >= 14:
            self.GLOBAL_STAT_VIEWS.append('pg_stat_wal')
        if self.dbms_major_version >= 16:
            self.GLOBAL_STAT_VIEWS.append('pg_stat_io')

        self.views = [
            self.GLOBAL_STAT_VIEWS,
            self.PER_DB_STAT_VIEWS,
        ]
        if self.per_table_metrics:
            self.views.append(self.PER_TABLE_STAT_VIEWS)

    def _get_views_cols(self):
        """ Get column names of views """

        def get_table_columns(table):
            query = f"""select column_name
                    from information_schema.columns
                    where table_name = '{table}';
                    """
            self.curs.execute(query)

            cols = [ t[0] for t in self.curs.fetchall() ]
            return cols

        views_cols = { }
        for v in self.views:
            for t in v:
                views_cols[t] = get_table_columns(t)

        return views_cols
