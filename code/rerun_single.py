import argparse
import json
import sys
from threading import Thread
from typing import Optional

import client.utils
import ConfigSpace as CS
import numpy as np
import pandas as pd
from client.reproducible import fix_global_random_state
from evaluation_client import Evaluator, EvaluatorClient
from proto import message_pb2


def parse_args() -> tuple[int, str, str]:
    parser = argparse.ArgumentParser()
    parser.add_argument("experiment_file")
    parser.add_argument("configs_file")
    parser.add_argument("output_file")
    parser.add_argument("--seed", type=int, default=1234, required=False)
    args = parser.parse_args()
    return args.seed, args.experiment_file, args.configs_file, args.output_file


def old_to_new(input_space: CS.ConfigurationSpace, config: dict, seed: int):
    new_config = dict(input_space.get_default_configuration()).copy()

    # if value is now illegal delete it
    if False:
        for key in list(config.keys()):
            if key not in new_config:
                continue
            try:
                val = float(config[key])
                if val < input_space[key].lower:
                    config[key] = input_space[key].lower
                    print(f"set lower: {key}")
                elif val > input_space[key].upper:
                    config[key] = input_space[key].upper
                    print(f"set upper: {key}")
            except:
                None

    # update old values into default list
    for key in new_config.keys():
        if key in config:
            new_config[key] = config[key]

    return new_config


def evaluate(
    clnt: Evaluator,
    config: dict,
    result: list[Optional[float]],
    index: int,
    input_space: CS.ConfigurationSpace,
    params: dict,
) -> None:
    cfg = client.utils.finalize_space_no_map(
        config, client.utils.configspace_to_metadata(input_space), **params
    )
    res: message_pb2.Performanace = clnt.evaluate(cfg)
    print(res)
    result[index] = res.throughput


def main() -> int:

    seed, experiment_filepath, configs_file, output_file = parse_args()
    shortname, _, benchmark, dbms, knobs, params, target, worst_score, timeout = (
        client.utils.get_experiment_info(experiment_filepath)
    )
    fix_global_random_state(seed=seed)

    input_space = client.utils.load_input_space(knobs, seed, **params)
    hosts = client.utils.load_hosts("hosts")
    config: pd.DataFrame = pd.read_csv(configs_file)["CleanConfig"].iloc[0]

    print(config)

    df_out: pd.DataFrame = pd.DataFrame(
        columns=["CleanConfig"] + [f"w{i}" for i, _ in enumerate(hosts)]
    )

    print(f"Starting config")
    results: list[Optional[float]] = [None] * len(hosts)
    threads: list[Thread] = [
        Thread(
            target=evaluate,
            args=(
                client.utils.host_to_evaluator(host, dbms, benchmark),
                old_to_new(input_space, json.loads(config.replace("'", '"')), seed),
                results,
                index,
                input_space,
                params,
            ),
        )
        for index, host in enumerate(hosts)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    df_out.loc[df_out.shape[0]] = [config] + results
    df_out.to_csv(output_file)


if __name__ == "__main__":
    sys.exit(main())
