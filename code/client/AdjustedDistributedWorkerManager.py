import copy
import json
import pickle
import traceback
from typing import Any, Callable

import client.utils
import mlos_core.optimizers
import numpy as np
import pandas as pd
from client.DistributedWorkerManager import DistributedWorkerManager
from client.WorkerManager import _default_stopping_criteria
from evaluation_client import Evaluator, EvaluatorClient
from proto import message_pb2


class AdjustedDistributedWorkerManager(DistributedWorkerManager):

    def __init__(
        self,
        model_type: type,
        shortname: str,
        seed: str,
        metadata: dict,
        params: dict,
        optimizer: mlos_core.optimizers.BaseOptimizer,
        eval_clients: list[Evaluator],
        extract_target: Callable[[Any], float],
        model_file: str = None,
        stopping_criteria: Callable[[int, int], bool] = _default_stopping_criteria,
        worst_score: float = 0,
        minimization: bool = False,
        timeout: float = 2400,
        file_prefix: str = "",
        skip_relative_range: bool = False,
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
            timeout=timeout,
        )

        self.model_type = model_type
        if model_file is not None:
            self._load_adjust_model(model_file)
        else:
            self.model = self.model_type(empty=True)
        self.minimization = minimization
        self.maximization = not minimization
        self.file_prefix = file_prefix
        self.skip_relative_range = skip_relative_range

        self.worker_columns_raw: list[str] = [
            f"w{i}_raw" for i in range(len(self.worker_columns))
        ]
        self.worker_columns_metrics: list[str] = [
            f"w{i}_metrics" for i in range(len(self.worker_columns))
        ]
        self.local_observations: pd.DataFrame = pd.DataFrame(
            columns=["CleanConfig", "Config", "Context", "Budget", "Reported Value"]
            + self.worker_columns
            + self.worker_columns_raw
            + self.worker_columns_metrics
        )

    def _load_adjust_model(self, model_file):
        with open(model_file, "rb") as f:
            self.model = pickle.load(f)

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
        raw_values = self.local_observations[
            self.local_observations["CleanConfig"] == clean_suggest_value
        ][self.worker_columns_raw].min()
        metrics = self.local_observations[
            self.local_observations["CleanConfig"] == clean_suggest_value
        ][self.worker_columns_metrics].bfill()
        if len(metrics) == 0:
            metrics = [np.nan for _ in metrics.columns]
        else:
            metrics = metrics.iloc[0]

        # append old values to list
        end = len(self.local_observations)
        self.local_observations.loc[end] = (
            [
                clean_suggest_value,
                suggested_value,
                context,
                budget,
                -1,  # Reported Value
            ]
            + list(values.values)
            + list(raw_values.values)
            + list(metrics)
        )
        return suggested_value, context

    def _run_worker(
        self, eval_client: EvaluatorClient, task: pd.Series, worker_id: int
    ):
        print(f"Trial {self.global_trials} Started")
        raw_worker_column: str = f"w{worker_id}_raw"
        metrics_column: str = f"w{worker_id}_metrics"
        try:
            response: message_pb2.Performanace = eval_client.evaluate(
                task["CleanConfig"]
            )
            # response = message_pb2.Performanace(
            #    throughput=worker_id + 10,
            #    latency=worker_id + 20,
            #    runtime=1234,
            #    metrics="{}",
            # )
            # store raw score and metrics in the results table
            with self.shared_lock:
                result_row = self._get_row(task)
                self.local_observations.loc[result_row, [raw_worker_column]] = (
                    self.extract_target(response)
                )
                # add one hot for worker id
                self.local_observations.loc[result_row, [metrics_column]] = json.dumps(
                    json.loads(response.metrics)
                    | {f"w{i}": worker_id == i for i in range(len(self.threads))}
                )

            score = self._score_adjuster(response, worker_id)
        except Exception as e:
            print(traceback.format_exc())
            print(f"Error, marked as failed: {e}")
            score = self.worst_score
            result_row = self._get_row(task)
            self.local_observations.loc[result_row, [raw_worker_column]] = score

        print(f"Trial {self.global_trials} Completed")
        with self.shared_lock:
            self.global_trials += 1

        return score

    def _get_relative_range(self, row: pd.DataFrame) -> float:
        if self.skip_relative_range:
            return 0

        try:
            return (
                ((row.max(axis=1) - row.min(axis=1)) / row.mean(axis=1)).abs().iloc[0]
            )
        except Exception as e:
            print(e)
            return 0

    def _default_score(self) -> pd.Series:
        return self.local_observations[self.worker_columns_raw].iloc[[0]].min(axis=1)

    def _update_score_optimizer(self, task):
        result_row = self._get_row(task)
        worker_values = self.local_observations.loc[result_row, self.worker_columns]
        raw_worker_values = self.local_observations.loc[
            result_row, self.worker_columns_raw
        ]
        metric_values = self.local_observations.loc[
            result_row, self.worker_columns_metrics
        ]
        budget = self.local_observations.loc[result_row, "Budget"]
        # this needs to only register if all the workers are done running and we have enough budget
        if (worker_values.min(axis=1) != -1).all() and (
            worker_values.count(axis=1) >= budget
        ).all():
            # always 0 on single entry
            relative_range: float = self._get_relative_range(raw_worker_values)
            default_score: pd.Series = self._default_score()
            raw_min: pd.Series = raw_worker_values.min(axis=1)
            raw_median: pd.Series = raw_worker_values.median(axis=1)
            raw_max: pd.Series = raw_worker_values.max(axis=1)

            if self.skip_relative_range:
                raw_min = raw_median
                raw_max = raw_median

            if self.minimization:
                # don't score crashing configs
                if len(default_score) > 0 and raw_max.iloc[0] > (
                    default_score.iloc[0] * 100
                ):
                    print("Raw score too high, returning unadjusted values")
                    reporting_score = raw_max
                # Magic number found from longitudinal study
                elif relative_range >= 0.3:
                    print(
                        "Variance too high, returning max(default value / 2, min raw score / 2)"
                    )
                    if default_score.iloc[0] is not np.nan:
                        reporting_score = pd.Series(
                            [max(default_score.iloc[0], raw_max.iloc[0]) * 2]
                        )
                    else:
                        reporting_score = pd.Series([0])
                else:
                    if self.skip_relative_range:
                        reporting_score = worker_values.median(axis=1)
                    else:
                        reporting_score = worker_values.max(axis=1)
            else:
                # don't score crashing configs
                if len(default_score) > 0 and raw_min.iloc[0] < (
                    default_score.iloc[0] / 100
                ):
                    print("Raw score too low, returning unadjusted values")
                    reporting_score = -raw_min
                # Magic number found from longitudinal study
                elif relative_range >= 0.3:
                    print(
                        "Variance too high, returning min(default value * 2, min raw score * 2)"
                    )
                    if default_score.iloc[0] is not np.nan:
                        reporting_score = -pd.Series(
                            [min(default_score.iloc[0], raw_min.iloc[0]) / 2]
                        )
                    else:
                        reporting_score = pd.Series([0])
                else:
                    if self.skip_relative_range:
                        reporting_score = -worker_values.median(axis=1)
                    else:
                        reporting_score = -worker_values.min(axis=1)

            # budget must be max
            if budget.iloc[0] == len(self.threads):
                self._update_model(
                    metric_values.dropna(axis=1).iloc[0].to_list(),
                    raw_worker_values.dropna(axis=1).iloc[0].to_list(),
                )
                # hack to make it so max budgets don't get adjusted
                # worker_values = raw_worker_values
                # worker_values.loc[:, :] = raw_worker_values.mean(axis=1).iloc[0]

            self.optimizer.register(task["Config"], reporting_score, task["Context"])
            self.local_observations.loc[result_row, "Reported Value"] = (
                reporting_score.iloc[0]
            )
            print(f"Iteration {self.iterations} Completed")
            self.iterations += 1

    def _update_model(self, metrics: list[str], scores: list[float]):
        df = self._metrics_to_dfs(metrics, scores)
        if df is not None:
            self.model.update_model(df)

    def _dump_model(self, location: str):
        self.model.dump(location)

    def _response_to_df(self, response: message_pb2.Config, worker_id: int):
        df = self._metrics_to_dfs([response.metrics], [self.extract_target(response)])
        return pd.concat(
            [
                df,
                pd.DataFrame(
                    {f"w{i}": [worker_id == i] for i in range(len(self.threads))}
                ),
            ],
            axis=1,
        )

    def _metrics_to_dfs(self, metrics: list[str], scores: list[float]):
        dfs = []
        for m, s in zip(metrics, scores):
            if m == np.nan:
                return None
            m_load: dict = json.loads(m)
            df = pd.DataFrame(m_load | {"Performance": [s]})
            dfs.append(df)

        if len(dfs) == 0:
            return None

        df = pd.concat(dfs)
        df["Average Performance"] = df["Performance"].mean()
        df["Normalized Performance"] = (
            df["Performance"] - df["Average Performance"]
        ) / df["Average Performance"]
        return df

    def _score_adjuster(self, response: message_pb2.Config, worker_id: int):
        df = self._response_to_df(response, worker_id)
        if df is None:
            relative_sore = 0
        else:
            relative_score = self.model.predict(df)[0]
        if relative_score == 0:
            print("Model Failed")
        return self.extract_target(response) / (1 + relative_score)
