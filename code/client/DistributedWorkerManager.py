import copy
import threading
import traceback
from typing import Any, Callable, Optional

import client.utils
import mlos_core.optimizers
import numpy as np
import pandas as pd
from client.WorkerManager import WorkerManager, _default_stopping_criteria
from evaluation_client import Evaluator, EvaluatorClient
from proto import message_pb2


class DistributedWorkerManager(WorkerManager):

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
        worst_score: float = 0,
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

        self.optimizer: mlos_core.optimizers.BaseOptimizer = optimizer

        self.eval_clients: list[Evaluator] = eval_clients
        self.extract_target: Callable[[Any], float] = extract_target
        self.stopping_criteria: Callable[[int, int], bool] = stopping_criteria

        self.worker_columns: list[str] = [f"w{i}" for i in range(len(eval_clients))]
        self.local_observations: pd.DataFrame = pd.DataFrame(
            columns=["CleanConfig", "Config", "Context", "Budget", "Reported Value"]
            + self.worker_columns
        )

        self.iterations: int = 0
        self.global_trials: int = 0
        self.worst_score: float = worst_score

        self.shared_lock: threading.Lock = threading.Lock()

        self.threads: list[threading.Thread] = [
            threading.Thread(target=self._client_manager, args=(eval_client, idx))
            for idx, eval_client in enumerate(self.eval_clients)
        ]

    def start(self) -> None:
        # Force some default configs
        _, self.dummy_context = self._get_new_task(True, len(self.threads))

        for thread in self.threads:
            thread.start()
        for thread in self.threads:
            thread.join()

    def _get_row(self, task: pd.Series) -> pd.Series:
        config_match = self.local_observations["CleanConfig"] == task["CleanConfig"]
        context_match = (
            self.local_observations["Context"].transform(lambda row: row.to_dict())
            == task["Context"].to_dict()
        )
        result_row = config_match & context_match
        return result_row

    def _get_new_task(self, force_default: bool = False, force_budget: int = None):
        # get a value from the optimizer
        suggested_value, context = self.optimizer.suggest(defaults=force_default)
        context = copy.copy(context)
        clean_suggest_value, budget = self._extract_values(suggested_value, context)

        if force_budget:
            budget = force_budget
            context.loc[0, "budget"] = force_budget

        # find old values
        values = self.local_observations[
            self.local_observations["CleanConfig"] == clean_suggest_value
        ][self.worker_columns].min()

        # append old values to list
        end = len(self.local_observations)
        self.local_observations.loc[end] = [
            clean_suggest_value,
            suggested_value,
            context,
            budget,
            -1,  # Reported Value
        ] + list(values.values)
        return suggested_value, context

    def _get_pending_tasks(self, worker_id: int):
        worker_column: str = f"w{worker_id}"
        under_budget = (
            self.local_observations[self.worker_columns].count(axis=1)
            < self.local_observations["Budget"]
        )
        worker_legal = self.local_observations[worker_column].isna()
        pending = self.local_observations[under_budget & worker_legal].reset_index()
        return pending

    def _client_manager(self, eval_client: EvaluatorClient, worker_id: int) -> None:
        worker_column: str = f"w{worker_id}"
        while self.stopping_criteria(self.iterations, self.global_trials):
            task: Optional[pd.Series] = None

            with self.shared_lock:
                while task is None:
                    pending = self._get_pending_tasks(worker_id)
                    if len(pending) != 0:
                        # get the first legal task from the list and set it as pending (-1)
                        task = pending.loc[0, ["CleanConfig", "Config", "Context"]]
                        result_row = self._get_row(task)
                        self.local_observations.loc[result_row, [worker_column]] = -1

                    # a task was not found so add a new one and retry
                    if task is None:
                        self._get_new_task()
                print(f"Pending Tasks: {len(pending)}")

            # Run the task
            score = self._run_worker(eval_client, task, worker_id)

            # register result
            with self.shared_lock:
                self._update_score_table(task, worker_column, score)

                try:
                    self.checkpoint()
                except Exception as e:
                    print(e)

                self._update_score_optimizer(task)

    def _update_score_table(self, task, worker_column, score):
        result_row = self._get_row(task)
        self.local_observations.loc[result_row, [worker_column]] = score

    def _update_score_optimizer(self, task):
        result_row = self._get_row(task)
        worker_values = self.local_observations.loc[result_row, self.worker_columns]
        # this needs to only register if all the workers are done running and we have enough budget
        if (worker_values.min(axis=1) != -1).all() and (
            worker_values.count(axis=1)
            >= self.local_observations.loc[result_row, "Budget"]
        ).all():
            if self.minimization:
                reported_value = worker_values.max(axis=1)
            else:
                reported_value = -worker_values.min(axis=1)
            self.optimizer.register(task["Config"], reported_value, task["Context"])
            self.local_observations.loc[result_row, "Reported Value"] = (
                reported_value.iloc[0]
            )
            print(f"Iteration {self.iterations} Completed")
            self.iterations += 1

    def _run_worker(
        self, eval_client: EvaluatorClient, task: pd.Series, worker_id: int
    ):
        print(f"Trial {self.global_trials} Started")
        try:
            # score = self.extract_target(
            #    message_pb2.Performanace(
            #        throughput=worker_id + 1, latency=worker_id + 2, runtime=1234
            #    )
            # )
            score = self.extract_target(eval_client.evaluate(task["CleanConfig"]))
        except Exception as e:
            print(traceback.format_exc())
            print(f"Error, marked as failed: {e}")
            score = self.worst_score
        print(f"Trial {self.global_trials} Completed")
        with self.shared_lock:
            self.global_trials += 1

        return score

    def get_observations(self) -> pd.DataFrame:
        observations: pd.DataFrame = self.local_observations.drop(columns=["Config"])
        observations["Context"] = observations["Context"].transform(
            lambda row: row.to_dict()
        )
        return observations
