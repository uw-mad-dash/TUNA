import threading
import traceback
from typing import Any, Callable

import client.utils
import mlos_core.optimizers
import pandas as pd
from client.WorkerManager import WorkerManager, _default_stopping_criteria
from evaluation_client import Evaluator, EvaluatorClient
from google.protobuf.json_format import MessageToDict
from proto.message_pb2 import Performanace


class ParallelWorkerManager(WorkerManager):

    def __init__(
        self,
        shortname: str,
        seed: str,
        metadata: dict,
        params: dict,
        optimizer: list[mlos_core.optimizers.BaseOptimizer],
        eval_clients: list[Evaluator],
        extract_target: Callable[[Any], float],
        stopping_criteria: Callable[[int, int], bool] = _default_stopping_criteria,
        worst_score: int = 0,
        minimization: bool = False,
        timeout: float = 2400,
        prior: Callable[[], float] = None,
        penalty: Callable[[int, dict[str, Any]], float] = None,
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
        self.prior = prior
        self.penalty = penalty

        self.shared_lock: threading.Lock = threading.Lock()
        self.observations: pd.DataFrame = pd.DataFrame(
            columns=[
                "Iteration",
                "CleanConfig",
                "Config",
                "Context",
                "Score",
                "Raw Score",
                "Worker",
                "Raw Data",
            ]
        )

        self.threads: list[threading.Thread] = [
            threading.Thread(
                target=self._run_worker, args=(metadata, params, opt, eval_client, idx)
            )
            for idx, (eval_client, opt) in enumerate(zip(eval_clients, optimizer))
        ]

    def start(self):
        for thread in self.threads:
            thread.start()
        for thread in self.threads:
            thread.join()

    def _run_worker(
        self,
        metadata: dict,
        params: dict,
        optimizer: mlos_core.optimizers.BaseOptimizer,
        eval_client: EvaluatorClient,
        worker_id: int,
    ) -> None:
        iterations: int = 0

        # Run the task
        while self.stopping_criteria(iterations, iterations):
            config, context = optimizer.suggest(defaults=iterations == 0)
            clean_config = client.utils.finalize_space(
                config.iloc[0].to_dict(), metadata, **params
            )

            print(f"Trial {iterations} Started")
            try:
                evaluation = Performanace(
                    throughput=1234,
                    latencyp50=1234,
                    latencyp95=1234,
                )
                # evaluation: Performanace = eval_client.evaluate(
                #    clean_config, timeout=self.timeout
                # )
                score = self.extract_target(evaluation)

            except Exception as e:
                print(traceback.format_exc())
                print(f"Error, marked as failed: {e}")
                score = self.worst_score
                evaluation = None
            print(f"Trial {iterations} Completed")

            # enables the use of a gaussian prior
            adj_score = score
            if self.prior:
                adj_score *= self.prior()
            if self.penalty:
                adj_score -= self.penalty(worker_id, clean_config)

            with self.shared_lock:
                self.observations.loc[len(self.observations)] = [
                    iterations,
                    clean_config,
                    config,
                    context,
                    adj_score,
                    score,
                    worker_id,
                    None if evaluation is None else MessageToDict(evaluation),
                ]
                self.checkpoint()
            if self.minimization:
                optimizer.register(config, pd.Series([adj_score]), context)
            else:
                optimizer.register(config, pd.Series([-adj_score]), context)
            iterations += 1

    def get_observations(self) -> pd.DataFrame:
        return self.observations.drop(columns=["Config"])
