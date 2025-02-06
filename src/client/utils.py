import argparse
import json
import logging
import math
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

import ConfigSpace as CS
import numpy as np
import pandas as pd
from evaluation_client import Evaluator, EvaluatorClient
from proto import message_pb2


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("experiment_filepath")
    parser.add_argument("seed", type=int, default=1234)
    parser.add_argument("hosts_filepath", type=str, default="hosts")
    args = parser.parse_args()
    return args.seed, args.experiment_filepath, args.hosts_filepath


def run_command(cmd, **kwargs):
    cp = None
    try:
        cp = subprocess.run(cmd, shell=True, **kwargs)
    except Exception as err:
        print(err)

    return cp


def parse_config_value(d: dict, key: str, **kwargs):
    if key not in d or d[key] == "":
        return np.nan
    try:
        return float(d[key])
    except ValueError:
        new_value = d[key]
        for name, val in kwargs.items():
            new_value = new_value.replace(name, str(val))
        return eval(new_value)


def parse_config_list(d: dict, key: str, **kwargs):
    if key not in d or d[key] == "":
        return []
    return list(map(lambda v: parse_config_value({0: v}, 0, **kwargs), d[key]))


def load_transfer_input_space(
    knobs: list[dict],
    transfer: dict[str, list[dict]],
    base_config: dict,
    seed: int,
    **kwargs,
) -> CS.ConfigurationSpace:
    input_space = CS.ConfigurationSpace(seed=seed)
    for k in knobs:
        if k["type"] == "enum":
            found = False
            for ov in transfer["overrides"]:
                if k["name"] == ov["name"]:
                    if "default" in ov:
                        hyperparameter = CS.CategoricalHyperparameter(
                            name=ov["name"],
                            choices=ov["choices"],
                            default_value=ov["default"],
                            meta=ov,
                        )
                    else:
                        hyperparameter = CS.CategoricalHyperparameter(
                            name=ov["name"],
                            choices=ov["choices"],
                            default_value=k["default"],
                            meta=ov,
                        )
                    found = True
                    break
            if not found:
                for dflt in transfer["defaults"]:
                    if dflt["target_type"] == "enum":
                        if "default" in dflt:
                            hyperparameter = CS.CategoricalHyperparameter(
                                name=k["name"],
                                choices=dflt["choices"],
                                default_value=dflt["default"],
                                meta=dflt,
                            )
                        else:
                            hyperparameter = CS.CategoricalHyperparameter(
                                name=k["name"],
                                choices=dflt["choices"],
                                default_value=k["default"],
                                meta=dflt,
                            )

        elif k["type"] == "real" or k["type"] == "int" or k["type"] == "integer":
            default_value = parse_config_value(k, "default", **kwargs)
            base_default = base_config[k["name"]]
            minval = parse_config_value(k, "min", **kwargs)
            maxval = parse_config_value(k, "max", **kwargs)
            epsilon = 0.000000001

            found = False
            for ov in transfer["overrides"]:
                if k["name"] == ov["name"]:
                    if base_default != 0:
                        low = max(
                            ov["min"],
                            k["min"] / base_default,
                        )
                        high = min(
                            ov["max"],
                            k["max"] / base_default,
                        )
                    else:
                        low = ov["min"]
                        high = ov["max"]

                    if ov["type"] == "integer":
                        hyperparameter = CS.UniformIntegerHyperparameter(
                            name=ov["name"],
                            lower=low,
                            upper=high,
                            default_value=max(
                                min(ov["default"], high - epsilon), low + epsilon
                            ),
                            meta=ov,
                        )
                        found = True
                        break
                    elif ov["type"] == "real":
                        hyperparameter = CS.UniformFloatHyperparameter(
                            name=ov["name"],
                            lower=low,
                            upper=high,
                            default_value=max(
                                min(ov["default"], high - epsilon), low + epsilon
                            ),
                            meta=ov,
                        )
                        found = True
                        break
            if not found:
                for dflt in transfer["defaults"]:
                    if dflt["target_type"] == k["type"]:
                        if base_default != 0:
                            low = max(
                                dflt["min"],
                                k["min"] / base_default,
                            )
                            high = min(
                                dflt["max"],
                                k["max"] / base_default,
                            )
                        else:
                            low = dflt["min"]
                            high = dflt["max"]

                        if dflt["type"] == "integer":
                            hyperparameter = CS.UniformIntegerHyperparameter(
                                name=k["name"],
                                lower=low,
                                upper=high,
                                default_value=max(
                                    min(dflt["default"], high - epsilon), low + epsilon
                                ),
                                meta=dflt,
                            )
                            break
                        elif dflt["type"] == "real":
                            hyperparameter = CS.UniformFloatHyperparameter(
                                name=k["name"],
                                lower=low,
                                upper=high,
                                default_value=max(
                                    min(dflt["default"], high - epsilon), low + epsilon
                                ),
                                meta=dflt,
                            )
                            break
        else:
            raise Exception(f'Unexpected type on knobs {k["name"]}')
        input_space.add_hyperparameter(hyperparameter)

    # add relations between knobs and illegal spaces
    for hyper in input_space:
        meta = input_space[hyper].meta
        if meta is None:
            continue
    return input_space


def load_input_space(knobs: dict, seed: int, **kwargs) -> CS.ConfigurationSpace:
    input_space = CS.ConfigurationSpace(seed=seed)
    for k in knobs:
        if k["type"] == "enum":
            hyperparameter = CS.CategoricalHyperparameter(
                name=k["name"],
                choices=k["choices"],
                default_value=k["default"],
                meta=k,
            )
        elif k["type"] == "real" or k["type"] == "int" or k["type"] == "integer":
            default_value = parse_config_value(k, "default", **kwargs)
            minval = parse_config_value(k, "min", **kwargs)
            maxval = parse_config_value(k, "max", **kwargs)
            print(k, minval, maxval)
            valrange = maxval - minval
            specialvalues = parse_config_list(k, "specialvalues", **kwargs)

            # give each special value 20% of the region
            d = 0
            for sv in specialvalues:
                if default_value == sv:
                    d += 0.1
                    break
                d += 0.2
            if default_value not in specialvalues:
                # bound default between min and max to prevent over or underflow
                default_value = max(min(default_value, maxval), minval)
                # scale value between remaining range
                d += ((default_value - minval) / valrange) * (1 - d)

            hyperparameter = CS.UniformFloatHyperparameter(
                name=k["name"],
                lower=0,
                upper=1,
                default_value=d,
                meta=k,
            )
        else:
            raise Exception(f'Unexpected type on knobs {k["name"]}')
        input_space.add_hyperparameter(hyperparameter)

    # add relations between knobs and illegal spaces
    for hyper in input_space:
        meta = input_space[hyper].meta
        if meta is None:
            continue
    return input_space


""" if "lessthan" in meta:
            input_space.add_forbidden_clause(
                CS.ForbiddenLessThanRelation(
                    input_space[hyper], input_space[meta["lessthan"]]
                )
            )
        if "greaterthan" in meta:
            input_space.add_forbidden_clause(
                CS.ForbiddenGreaterThanRelation(
                    input_space[hyper], input_space[meta["greaterthan"]]
                )
            )"""


def configspace_to_metadata(config: CS.ConfigurationSpace, **params) -> dict:
    metadata = {}
    for key in config:
        if config[key] is not None:
            metadata[key] = config[key].meta
    return metadata


def value_eval(val, **params):
    try:
        return float(val)
    except ValueError:
        new_value = val
        for name, v in params.items():
            new_value = new_value.replace(name, str(v))
        return eval(new_value)


def finalize_space_no_map(config: dict, metadata: dict, **params: dict) -> dict:
    final = {}
    retry_list = config.items()
    depth = 0

    while len(retry_list) > 0 and depth < 10:
        new_retry_list = []
        depth += 1

        for k, v in retry_list:
            meta = metadata[k]
            # this should never be true
            if meta is None:
                # logging.warn("meta is null in finalize space")
                final[k] = v
                continue
            if "exclude" in meta:
                if meta["exclude"] == True:
                    continue

            # rescale numeric types for special values
            if meta["type"] == "int" or meta["type"] == "real":
                maxval = value_eval(meta["max"], **params)
                minval = value_eval(meta["min"], **params)
                try:
                    if "lessthan" in meta:
                        maxval = min(
                            maxval, value_eval(meta["lessthan"], **(params | final))
                        )
                    if "greaterthan" in meta:
                        minval = max(
                            minval, value_eval(meta["greaterthan"], **(params | final))
                        )
                except Exception as e:
                    new_retry_list += [(k, v)]
                    continue

            if meta["type"] == "int":
                v = int(v)

            if "dropvalues" in meta:
                if v in meta["dropvalues"]:
                    continue

            if "prefix" in meta:
                v = meta["prefix"] + str(v)
            if "suffix" in meta:
                v = str(v) + meta["suffix"]

            if "group" in meta:
                if meta["group"] in final:
                    final[meta["group"]] += f",{k}={v}"
                else:
                    final[meta["group"]] = f"{k}={v}"
                continue
            elif "group2" in meta:
                if meta["group2"] in final:
                    final[meta["group2"]] += f" {v}"
                else:
                    final[meta["group2"]] = str(v)
                continue

            final[k] = v

        retry_list = new_retry_list

    return final


def unfinalize_space(config: dict, knobs: dict, **kwargs) -> dict:
    unfinal_config = {}
    for k in knobs:
        if k["name"] not in config:
            continue

        if k["type"] == "enum":
            unfinal_config[k["name"]] = config[k["name"]]
        elif k["type"] == "real" or k["type"] == "int" or k["type"] == "integer":
            default_value = config[k["name"]]
            minval = parse_config_value(k, "min", **kwargs)
            maxval = parse_config_value(k, "max", **kwargs)
            valrange = maxval - minval
            specialvalues = parse_config_list(k, "specialvalues", **kwargs)

            # give each special value 20% of the region
            d = 0
            for sv in specialvalues:
                if default_value == sv:
                    d += 0.1
                    break
                d += 0.2
            if default_value not in specialvalues:
                # bound default between min and max to prevent over or underflow
                default_value = max(min(default_value, maxval), minval)
                # scale value between remaining range
                d += ((default_value - minval) / valrange) * (1 - d)

            unfinal_config[k["name"]] = d
        else:
            raise Exception(f'Unexpected type on knobs {k["name"]}')
    return unfinal_config


def finalize_space(config: dict, metadata: dict, **params: dict) -> dict:
    final = {}
    retry_list = config.items()
    depth = 0

    while len(list(retry_list)) > 0 and depth < 10:
        new_retry_list = []
        depth += 1

        for k, v in retry_list:
            meta = metadata[k]
            # this should never be true
            if meta is None:
                # logging.warn("meta is null in finalize space")
                final[k] = v
                continue
            if "exclude" in meta:
                if meta["exclude"] == True:
                    continue

            # rescale numeric types for special values
            if meta["type"] == "integer" or meta["type"] == "real":
                maxval = value_eval(meta["max"], **params)
                minval = value_eval(meta["min"], **params)
                try:
                    if "lessthan" in meta:
                        maxval = min(
                            maxval, value_eval(meta["lessthan"], **(params | final))
                        )
                    if "greaterthan" in meta:
                        minval = max(
                            minval, value_eval(meta["greaterthan"], **(params | final))
                        )
                except Exception as e:
                    new_retry_list += [(k, v)]
                    continue

                d = 0
                found = False
                if "specialvalues" in meta:
                    for sv in meta["specialvalues"]:
                        if d < v and v < d + 0.2:
                            v = sv
                            found = True
                            break
                        d += 0.2
                if not found:
                    v = ((v - d) / (1 - d)) * (maxval - minval) + minval
            elif meta["type"] == "enum" and type(v) is not str and type(v) is not np.str_:
                
                print(type(v))
                partitions = 1 / len(meta["choices"])
                v = meta["choices"][min(int(v // partitions), len(meta["choices"]) - 1)]

            if meta["type"] == "integer" and not math.isnan(v):
                if "blocksize" in meta:
                    v = round(float(v) / float(meta["blocksize"])) * int(
                        meta["blocksize"]
                    )
                else:
                    v = round(v)

            if meta["type"] == "int":
                v = int(v)

            if "dropvalues" in meta:
                if v in meta["dropvalues"]:
                    continue

            if "prefix" in meta:
                v = meta["prefix"] + str(v)
            if "suffix" in meta:
                v = str(v) + meta["suffix"]

            if "group" in meta:
                if meta["group"] in final:
                    final[meta["group"]] += f",{k}={v}"
                else:
                    final[meta["group"]] = f"{k}={v}"
                continue
            elif "group2" in meta:
                if meta["group2"] in final:
                    final[meta["group2"]] += f" {v}"
                else:
                    final[meta["group2"]] = str(v)
                continue

            final[k] = v

        retry_list = new_retry_list

    return final


def finalize_transfer_space(
    baseconfig: dict[str, str | float],
    config: dict[str, pd.Series],
    apply: int,
    knobs: list[dict[str, Any]],
) -> dict:
    knob_dict = {i["name"]: i for i in knobs}

    final_config: dict[str, str | float] = deepcopy(baseconfig)
    for _ in range(apply):
        for k in config.keys():
            if type(final_config[k]) is str:
                final_config[k] = config[k]
            elif type(final_config[k]) is int:
                final_config[k] = round(final_config[k] * config[k])
            else:
                final_config[k] *= config[k]
        mn = knob_dict[k]["min"]
        mx = knob_dict[k]["max"]
        final_config[k] = max(mn, min(mx, final_config[k]))
    return final_config


def get_experiment_info(
    experiment_filepath: str,
) -> tuple[
    str,
    str,
    dict[str, str],
    dict[str, str],
    list[dict[str, Any]],
    dict[str, str],
    str,
    float,
    float,
]:
    with open(experiment_filepath) as f:
        expr = json.load(f)
        path = Path(experiment_filepath).parent

    with open(path / Path(expr["benchmark"])) as f:
        benchmark = json.load(f)
    with open(path / Path(expr["dbms"])) as f:
        dbms = json.load(f)
    with open(path / Path(expr["knobs"])) as f:
        knobs = json.load(f)
    with open(path / Path(expr["params"])) as f:
        params = json.load(f)

    return (
        expr["shortname"],
        expr["description"],
        benchmark,
        dbms,
        knobs,
        params,
        expr["target"],
        expr["worst_score"],
        expr["timeout"],
    )


def get_multi_experiment_info(
    experiment_filepath: str,
) -> tuple[
    str,
    str,
    dict[str, str],
    dict[str, str],
    list[dict[str, Any]],
    dict[str, str],
    str,
    float,
    float,
]:
    with open(experiment_filepath) as f:
        expr = json.load(f)
        path = Path(experiment_filepath).parent

    with open(path / Path(expr["benchmark"])) as f:
        benchmark = json.load(f)
    with open(path / Path(expr["dbms"])) as f:
        dbms = json.load(f)
    with open(path / Path(expr["knobs"])) as f:
        knobs = json.load(f)

    params = []
    for p in expr["params"]:
        with open(path / Path(p)) as f:
            params.append(json.load(f))

    return (
        expr["shortname"],
        expr["description"],
        benchmark,
        dbms,
        knobs,
        params,
        expr["target"],
        expr["worst_score"],
        expr["timeout"],
    )


def get_transfer_experiment_info(
    experiment_filepath: str,
) -> tuple[
    str,
    str,
    dict[str, str],
    dict[str, str],
    list[dict[str, str]],
    dict[str, str],
    str,
    float,
    float,
    dict[str, list[dict[str, str]]],
    dict[str, str],
]:
    tup = get_experiment_info(experiment_filepath)

    with open(experiment_filepath) as f:
        expr = json.load(f)
        path = Path(experiment_filepath).parent
    with open(path / Path(expr["transfer"])) as f:
        transfer = json.load(f)
    with open(path / Path(expr["baseconfig"])) as f:
        baseconfig = json.load(f)

    return tup + (transfer, baseconfig)


def host_to_evaluator(
    host: str,
    dbms_info: dict[str, str],
    benchmark_info: dict[str, str],
    metrics: bool = False,
) -> Evaluator:
    return EvaluatorClient(
        host=host, dbms_info=dbms_info, benchmark_info=benchmark_info, metrics=metrics
    )


def extract_target(target="throughput") -> Callable[[message_pb2.Performanace], float]:
    if target == "throughput":
        return lambda result: result.throughput
    elif target == "goodput":
        return lambda result: result.goodput
    elif target == "latencyp50":
        return lambda result: result.latencyp50
    elif target == "latencyp95":
        return lambda result: result.latencyp95
    elif target == "latencyp99":
        return lambda result: result.latencyp99
    elif target == "runtime":
        return lambda result: result.runtime
    return lambda result: result.throughput


def load_hosts(host_file: str) -> list[str]:
    try:
        with open(host_file) as f:
            hosts = f.readlines()
    except Exception as e:
        print("Expected properly formatted hosts file")
        raise e
    return hosts
