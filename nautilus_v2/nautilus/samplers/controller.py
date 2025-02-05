import json
import logging

from nautilus.dbms import DBMS
from nautilus.samplers.dbms import DBMSMetricsSampler
from nautilus.samplers import SamplerInterface

AVAILABLE_SAMPLERS = {
    'DBMSMetricsSampler': DBMSMetricsSampler,
}

class SamplersController:
    """Controller for sampler instances """
    _logger_name = __name__

    def __init__(self, dbms: DBMS, info: dict | None) -> None:
        self.logger = logging.getLogger(self._logger_name)
        self.dbms = dbms

        info = info or { }

        # Initialize samplers
        self.samplers: dict[str, SamplerInterface] = { }
        for name, sampler_info in info.items():

            class_ = AVAILABLE_SAMPLERS.get(sampler_info['class'], None)
            if class_ is None:
                raise ValueError(f'Unsupported sampler class: {sampler_info["class"]}')

            kwargs = sampler_info.get('kwargs', {})
            self.samplers[name] = class_.create(name, dbms, **kwargs)

            self.logger.info(f"Added `{name}' logger")

    def setup(self) -> None:
        # Initialize samplers
        for name, instance in self.samplers.items():
            self.logger.debug(f'Setting-up {name} sampler')
            instance.setup()

    def start(self) -> None:
        for name, instance in self.samplers.items():
            self.logger.debug(f'Starting {name} sampler')
            instance.start()

    def stop(self, **kwargs) -> None:
        for name, instance in self.samplers.items():
            self.logger.debug(f'Stopping {name} sampler..')
            instance.stop(**kwargs)

    def get_results(self):
        results: dict[str, dict[str, list]] = { }
        for name, instance in self.samplers.items():
            samples = instance.get_samples()
            samples['timestamps'] = [
                ts.isoformat() for ts in samples['timestamps'] ]

            results[name] = samples

        with open('/nautilus/samples.json', 'w') as f:
            json.dump(results, f, indent=2)
        with open('/nautilus/samples.pickle', 'wb') as f:
            import pickle
            pickle.dump(results, f)

        return results

