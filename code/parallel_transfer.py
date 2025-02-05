import argparse
import json
import sys

import client.utils
import mlos_core.optimizers
import pandas as pd
from client.ParallelTransferWorkerManager import ParallelTransferWorkerManager
from client.reproducible import fix_global_random_state


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("experiment_filepath")
    parser.add_argument("seed", type=int, default=1234)
    parser.add_argument("hosts_filepath", type=str)
    parser.add_argument("baseconfig", type=str)
    args = parser.parse_args()
    seed, experiment_filepath, hosts_filepath, baseconfig = (
        args.seed,
        args.experiment_filepath,
        args.hosts_filepath,
        args.baseconfig,
    )
    with open(baseconfig) as f:
        baseconfig = json.load(f)

    fix_global_random_state(seed=seed)

    (
        shortname,
        _,
        benchmark,
        dbms,
        knobs,
        params,
        target,
        worst_score,
        timeout,
        transfer,
        _,
    ) = client.utils.get_transfer_experiment_info(experiment_filepath)

    input_space = client.utils.load_transfer_input_space(
        knobs, transfer, baseconfig, seed, **params
    )

    hosts = client.utils.load_hosts(hosts_filepath)

    optimizers = [
        mlos_core.optimizers.SmacOptimizer(
            max_trials=50, seed=idx + seed, parameter_space=input_space, n_random_init=0
        )
        for idx, _ in enumerate(hosts)
    ]

    manager = ParallelTransferWorkerManager(
        metadata=client.utils.configspace_to_metadata(input_space),
        params=params,
        optimizer=optimizers,
        eval_clients=[
            client.utils.host_to_evaluator(
                host=host, dbms_info=dbms, benchmark_info=benchmark
            )
            for host in hosts
        ],
        extract_target=client.utils.extract_target(target),
        worst_score=worst_score,
        stopping_criteria=lambda iter, trial: iter < 50,
        minimization=("latency" in target or target == "runtime"),
        timeout=timeout,
        shortname=shortname,
        seed=seed,
        base_config=baseconfig,
    )
    manager.start()

    observations: pd.DataFrame = manager.get_observations()

    observations.to_csv(f"results/parallel_{shortname}s{seed}.csv")


if __name__ == "__main__":
    sys.exit(main())
