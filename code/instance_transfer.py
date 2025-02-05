import logging
import random
import sys

import client.utils
import mlos_core.optimizers
import pandas as pd
from client.NoClusterModel import NoClusterModel
from client.OracleAdjustedDistributedWorkerManager import (
    OracleAdjustedDistributedWorkerManager,
)
from client.reproducible import fix_global_random_state
from ConfigSpace import ConfigurationSpace
from ConfigSpace.hyperparameters import UniformFloatHyperparameter
from smac import MultiFidelityFacade as MFFacade
from smac.intensifier.successive_halving import SuccessiveHalving


def main() -> int:
    cs = ConfigurationSpace()
    alpha = UniformFloatHyperparameter("alpha", 0, 1, default_value=1.0)
    beta = UniformFloatHyperparameter("beta", 0, 1, default_value=1.0)
    cs.add_hyperparameters([alpha, beta])

    optimizer = mlos_core.optimizers.SmacOptimizer(
        seed=1,
        parameter_space=cs,
        facade=MFFacade,
        intensifier=SuccessiveHalving,
        # min_budget=int(1),
        # max_budget=int(8),
        instances=["a", "b", "c"],
        instance_features={
            "a": [1, 1],
            "b": [0, 2],
            "c": [3, 1],
        },
        instance_seed_order="None",
        # eta=2,
    )

    while True:
        cfg, ctx = optimizer.suggest()
        print(cfg)
        print(ctx)
        optimizer.register(cfg, pd.Series([float(input())]), ctx)


if __name__ == "__main__":
    sys.exit(main())
