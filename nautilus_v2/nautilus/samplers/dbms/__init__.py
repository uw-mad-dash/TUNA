
from nautilus.samplers import SamplerInterface
from nautilus.samplers.dbms.postgres import PostgreSQLMetricsSampler

class DBMSMetricsSampler:
    _logger_name = __name__

    @staticmethod
    def create(name, dbms, **kwargs) -> SamplerInterface:
        if dbms.name == 'postgres':
            return PostgreSQLMetricsSampler(name, dbms, **kwargs)
        else:
            raise ValueError(f'Unsupported DBMS: {dbms.name}')
