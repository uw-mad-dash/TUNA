import logging
import sys

import client.utils
import mlos_core.optimizers
import pandas as pd
from client.AdjustedDistributedWorkerManager import AdjustedDistributedWorkerManager
from client.PassthroughModel import PassthroughModel
from client.reproducible import fix_global_random_state
from smac import MultiFidelityFacade as MFFacade
from smac.intensifier.successive_halving import SuccessiveHalving


def main() -> int:
    seed, experiment_filepath, hosts_filepath = client.utils.parse_args()
    shortname, _, benchmark, dbms, knobs, params, target, worst_score, timeout = (
        client.utils.get_experiment_info(experiment_filepath)
    )

    logging.root.setLevel(logging.NOTSET)
    fix_global_random_state(seed=seed)

    input_space = client.utils.load_input_space(knobs, seed, **params)
    hosts = client.utils.load_hosts(hosts_filepath)

    optimizer = mlos_core.optimizers.SmacOptimizer(
        seed=seed,
        parameter_space=input_space,
        facade=MFFacade,
        intensifier=SuccessiveHalving,
        min_budget=int(1),
        max_budget=len(hosts),
    )  # instances=['a', 'b', 'c'], instance_features={'a': [0,1], 'b': [0,1], 'c': [0,1]})

    manager = AdjustedDistributedWorkerManager(
        model_type=PassthroughModel,
        shortname=shortname,
        seed=seed,
        metadata=client.utils.configspace_to_metadata(input_space),
        params=params,
        optimizer=optimizer,
        eval_clients=[
            client.utils.host_to_evaluator(
                host=host, dbms_info=dbms, benchmark_info=benchmark, metrics=True
            )
            for host in hosts
        ],
        extract_target=client.utils.extract_target(target),
        worst_score=worst_score,
        stopping_criteria=lambda iter, trial: trial < 500,
        minimization=(target == "latency" or target == "runtime"),
        timeout=timeout,
        file_prefix="ablation_outlier",
        skip_relative_range=True,
    )
    manager.start()

    observations: pd.DataFrame = manager.get_observations()
    observations.to_csv(f"results/ablation_seed{seed}.csv")


if __name__ == "__main__":
    sys.exit(main())
