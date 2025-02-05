import datetime
import json
import pickle
import threading
import traceback
from abc import ABC, abstractmethod
from typing import Any, Callable, Optional

import client.utils
import ConfigSpace as CS
import mlos_core.optimizers
import numpy as np
import pandas as pd
from evaluation_client import Evaluator, EvaluatorClient
from proto import message_pb2


def _default_stopping_criteria(iteration, global_trials):
    return global_trials < 500


class WorkerManager(ABC):

    def __init__(
        self,
        shortname: str,
        seed: str,
        metadata: dict,
        params: dict,
        minimization: bool,
        timeout: float,
    ):
        self.shortname = shortname
        self.seed = seed
        self.metadata = metadata
        self.params = params
        self.minimization = minimization
        self.timeout = timeout

    @abstractmethod
    def start(self):
        pass

    @abstractmethod
    def get_observations(self) -> pd.DataFrame:
        pass

    def checkpoint(self) -> None:
        observations: pd.DataFrame = self.get_observations()
        dest = f"results/{type(self).__name__}_{self.shortname}-seed{self.seed}"
        observations.to_csv(f"{dest}.csv")
        observations.to_parquet(f"{dest}.parquet")

    def _extract_values(
        self, suggested_value: pd.DataFrame, context: pd.DataFrame
    ) -> tuple[dict, int]:
        clean_suggest_value = client.utils.finalize_space(
            suggested_value.iloc[0].to_dict(), self.metadata, **self.params
        )
        budget = int(np.floor(context.loc[0, "budget"] or 1))
        return clean_suggest_value, budget
