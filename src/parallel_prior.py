import argparse
import sys

import client.utils
import mlos_core.optimizers
import numpy as np
import pandas as pd
from client.ParallelWorkerManager import ParallelWorkerManager
from client.reproducible import fix_global_random_state


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("experiment_filepath")
    parser.add_argument("seed", type=int, default=1234)
    parser.add_argument("hosts_filepath", type=str, default="hosts")
    parser.add_argument("noise", type=float)
    args = parser.parse_args()

    seed, experiment_filepath, hosts_filepath, noise = (
        args.seed,
        args.experiment_filepath,
        args.hosts_filepath,
        args.noise,
    )
    shortname, _, benchmark, dbms, knobs, params, target, worst_score, timeout = (
        client.utils.get_experiment_info(experiment_filepath)
    )

    print(noise)

    fix_global_random_state(seed=seed)

    input_space = client.utils.load_input_space(knobs, seed, **params)
    hosts = client.utils.load_hosts(hosts_filepath)

    optimizers = [
        mlos_core.optimizers.SmacOptimizer(
            max_trials=200, seed=seed, parameter_space=input_space
        )
        for _ in hosts
    ]

    prior = lambda: np.random.normal(1, noise, 1)[0]

    manager = ParallelWorkerManager(
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
        stopping_criteria=lambda iter, trial: iter < 100,
        minimization=("latency" in target or target == "runtime"),
        timeout=timeout,
        shortname=shortname,
        seed=seed,
        prior=prior,
    )
    manager.start()

    observations: pd.DataFrame = manager.get_observations()

    observations.to_csv(f"results/parallel_{shortname}-s{seed}-{noise}.csv")


if __name__ == "__main__":
    sys.exit(main())
