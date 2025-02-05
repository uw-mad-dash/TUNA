import datetime
import json
from typing import Any, Callable

import mlos_core.optimizers
import pandas as pd
from client.NaiveWorkerManager import NaiveWorkerManager
from client.WorkerManager import _default_stopping_criteria
from evaluation_client import Evaluator, EvaluatorClient
from proto import message_pb2


class MeasuredNaiveWorkerManager(NaiveWorkerManager):

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
            optimizer=optimizer,
            eval_clients=eval_clients,
            extract_target=extract_target,
            stopping_criteria=stopping_criteria,
            worst_score=worst_score,
            minimization=minimization,
            timeout=timeout,
        )
        self.timing_events: pd.DataFrame = pd.DataFrame(
            columns=["Iteration", "Worker", "start", "end"]
        )
        self.metrics: list[dict] = []

    def _run_worker(
        self,
        clean_config: dict,
        config: pd.DataFrame,
        eval_client: EvaluatorClient,
        worker_id: int,
        index: int,
    ):
        start = datetime.datetime.now()
        response: message_pb2.Performanace = super()._run_worker(
            clean_config, config, eval_client, worker_id, index
        )
        end = datetime.datetime.now()

        with self.shared_lock:
            self.timing_events.loc[len(self.timing_events)] = [
                index,
                f"w{worker_id}",
                start,
                end,
            ]

        try:
            metrics: dict = json.loads(response.metrics)
            metrics |= {"Iteration": index, "Worker": f"w{worker_id}"}
            with self.shared_lock:
                self.metrics.append(metrics)
        except Exception as e:
            print("Failed to parse metrics", e)

    def get_observations(self) -> pd.DataFrame:
        # reform metrics into dataframe
        metrics = pd.DataFrame(self.metrics)

        # left outer join
        df2 = pd.merge(
            self.timing_events, metrics, on=["Iteration", "Worker"], how="left"
        )
        # pivot table sideways
        col = list(df2.drop(columns=["Iteration", "Worker"]).columns)
        df2 = df2.pivot_table(col, ["Iteration"], "Worker", aggfunc="first")

        df1 = self.observations.drop(columns=["Config"])

        # left join
        df = pd.concat([df1, df2], axis=1).reindex(df1.index)

        return df
