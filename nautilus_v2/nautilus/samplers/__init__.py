
import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from threading import Event, Thread

class StoppableThread(Thread):
    """ Thread class with a stop() method.

    The thread itself has to check regularly for the stopped() condition.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._stop_event = Event()

    def stop(self):
        self._stop_event.set()

    def stopped(self):
        return self._stop_event.is_set()

class SamplerInterface(ABC):
    """ Abstract class for samplers """
    logger: logging.Logger

    def __init__(self, name, interval: int | None = None) -> None:
        self.name = name
        if interval is None:
            self.logger.error('Sampler interval not set')
            raise ValueError('Sampler interval not set')
        self.interval = interval

    def setup(self) -> None:
        self.samples = [ ]
        self.timestamps = [ ]

        self._thread = StoppableThread(target=self._do_sampling)

    def start(self):
        self._thread.start()

    def stop(self, timeout: int | None = 10, max_tries: int = 3):
        """ Stop the sampling thread  """
        self._thread.stop()

        for idx in range(max_tries):
            self._thread.join(timeout=timeout)
            if not self._thread.is_alive():
                return

            self.logger.debug(f'[try #{idx}] Failed to stop thread...')

        self.logger.warning(
            'Sampling thread could not be terminated! '
            'Check whether extra logic to timeout some operation(s) is needed.')

    def teardown(self):
        pass

    def get_samples(self):
        return {
            'samples': self.samples,
            'timestamps': self.timestamps,
        }

    @abstractmethod
    def sample(self, *args, **kwargs):
        raise NotImplementedError()

    def _do_sampling(self):
        """ Sampling loop executed by thread """
        self.logger.info('Sampling thread started!')

        while not self._thread.stopped():
            start = datetime.now()
            self.sample()

            elapsed = (datetime.now() - start).total_seconds()
            self.logger.debug(f'Sampling took: {elapsed * 1000: .2f} ms')

            if elapsed > self.interval:
                self.logger.warning(
                    f'Sampling took longer than interval: {elapsed:.2f} secs. '
                    'Consider increasing the interval / decreasing the sampling load.')
                continue

            # Sleep for the remaining time
            # NOTE: need to sleep in small intervals to be able to stop the thread
            total_sleep_time = self.interval - elapsed
            wake_up_time = datetime.now() + timedelta(seconds=total_sleep_time)
            self.logger.debug(f'Next sampling at: {wake_up_time}')

            while True:
                now = datetime.now()
                if now >= wake_up_time or self._thread.stopped():
                    break

                sleep_time = min((wake_up_time - now).total_seconds(), 0.5)
                time.sleep(sleep_time)

        self.teardown()
        self.logger.info('Sampling thread exiting!')
