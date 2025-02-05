import threading
import traceback
from typing import Any, Callable

import client.utils
import mlos_core.optimizers
import numpy as np
import pandas as pd
from client.WorkerManager import WorkerManager, _default_stopping_criteria
from evaluation_client import Evaluator, EvaluatorClient
from proto import message_pb2


class NaiveWorkerManager(WorkerManager):

    def __init__(
        self,
        shortname: str,
        seed: str,
        metadata: dict,
        params: dict,
        optimizer: mlos_core.optimizers.BaseOptimizer,
        eval_clients: list[Evaluator],
        extract_target: Callable[[Any], float],
        stopping_criteria: Callable[[int, int], bool] = _default_stopping_criteria,
        worst_score: int = 0,
        minimization: bool = False,
        timeout: float = 2400,
    ):
        super().__init__(
            shortname=shortname,
            seed=seed,
            metadata=metadata,
            params=params,
            minimization=minimization,
            timeout=timeout,
        )

        self.extract_target = extract_target
        self.stopping_criteria = stopping_criteria
        self.worst_score = worst_score

        self.shared_lock: threading.Lock = threading.Lock()
        self.worker_columns = list(map(lambda i: f"w{i}", range(len(eval_clients))))
        self.observations: pd.DataFrame = pd.DataFrame(
            columns=["Iteration", "CleanConfig", "Config", "Context", "Reported"]
            + self.worker_columns
        )
        self.optimizer = optimizer
        self.eval_clients = eval_clients

    def start(self):
        # Run the task
        iterations: int = 0
        while self.stopping_criteria(iterations, iterations):
            config, context = self.optimizer.suggest(defaults=iterations == 0)
            clean_config = client.utils.finalize_space(
                config.iloc[0].to_dict(), self.metadata, **self.params
            )

            print(f"Trial {iterations} Started")
            self.observations.loc[len(self.observations)] = [
                iterations,
                clean_config,
                config,
                context,
                -1,
            ] + list(np.zeros(len(self.eval_clients)))
            self.threads: list[threading.Thread] = [
                threading.Thread(
                    target=self._run_worker,
                    args=(clean_config, config, eval_client, idx, iterations),
                )
                for idx, (eval_client) in enumerate(self.eval_clients)
            ]

            for thread in self.threads:
                thread.start()
            for thread in self.threads:
                thread.join()

            if self.minimization:
                reported_value = self.observations.loc[
                    len(self.observations) - 1, self.worker_columns
                ].max()
            else:
                reported_value = -self.observations.loc[
                    len(self.observations) - 1, self.worker_columns
                ].min()

            self.observations.loc[len(self.observations) - 1, "Reported"] = (
                reported_value
            )
            self.optimizer.register(config, pd.Series([reported_value]), context)

            print(f"Trial {iterations} Completed")
            iterations += 1
            try:
                self.checkpoint()
            except Exception as e:
                print(e)

    def _run_worker(
        self,
        clean_config: dict,
        config: pd.DataFrame,
        eval_client: EvaluatorClient,
        worker_id: int,
        index: int,
    ) -> message_pb2.Performanace:
        try:
            # response = message_pb2.Performanace(
            #    throughput=worker_id + 1,
            #    latency=worker_id + 2,
            #    runtime=1234,
            #    metrics="{}",
            # )
            # score = self.extract_target(response)
            response = eval_client.evaluate(clean_config)
            score = self.extract_target(response)
        except Exception as e:
            print(traceback.format_exc())
            print(f"Error, marked as failed: {e}")
            score: float = self.worst_score
            response = None

        with self.shared_lock:
            self.observations.loc[index, f"w{worker_id}"] = score

        # needed for children who call into this class
        return response

    def get_observations(self) -> pd.DataFrame:
        return self.observations.drop(columns=["Config"])
