import argparse
import json
import logging
import sys
from threading import Thread
from typing import Optional

import ConfigSpace as CS
import numpy as np
import pandas as pd
import setup
from client import utils
from client.reproducible import fix_global_random_state
from evaluation_client import Evaluator, EvaluatorClient
from proto import message_pb2


def parse_args() -> tuple[int, str, str]:
    parser = argparse.ArgumentParser()
    parser.add_argument("configs_file")
    parser.add_argument("output_file")
    parser.add_argument("--seed", type=int, default=1234, required=False)
    args = parser.parse_args()
    return args.seed, args.configs_file, args.output_file


def old_to_new(config: dict, seed: int):
    input_space = utils.load_input_space("spaces/knobs/mysql-8.3.json", seed)
    new_config = dict(input_space.get_default_configuration()).copy()

    # if value is now illegal delete it
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
    client: Evaluator, config: dict, result: list[Optional[float]], index: int
) -> None:
    result[index] = client.evaluate(config).throughput


# BROKEN NEEDS TO BE UPDATED TO NEW VERSION of setup.host_to_evaluator
def main() -> int:
    seed, configs_file, output_file = parse_args()

    logging.root.setLevel(logging.NOTSET)
    fix_global_random_state(seed=seed)

    hosts = setup.load_hosts("hosts")
    configs: pd.DataFrame = pd.read_csv(configs_file)["CleanConfig"]

    df_out: pd.DataFrame = pd.DataFrame(
        columns=["CleanConfig"] + [f"w{i}" for i, _ in enumerate(hosts)]
    )

    for idx, config in enumerate(configs):
        print(f"Starting config {idx}")
        results: list[Optional[float]] = [None] * len(hosts)
        threads: list[Thread] = [
            Thread(
                target=evaluate,
                args=(
                    setup.host_to_evaluator(host),
                    old_to_new(json.loads(config.replace("'", '"')), seed),
                    results,
                    index,
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
