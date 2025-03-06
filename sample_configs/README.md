# Configuration Dataset

This folder contains the configurations which we found during the tuning runs presented in the [TUNA paper](https://aka.ms/mlos/tuna-eurosys-paper).

At a high level, configurations which were tuned in the South Central US Azure region are under the `azure` folder, configurations tuned in the Central US Azure region are in the `azure_centralus` folder, and the configurations found in CloudLab are under `cloudlab`.

For azure, we use exclusively `D8s_v5` nodes, and for CloudLab we use exclusively `c220g5` nodes.

Deploying these in environments that are not representative of their tuning environment can have unpredictable results.

## Uses

Rather than simply used for deployment (which as noted, is a limited set), by releasing this data we intend to allow further research into topics such as:

- advanced search methodology for improved convergence rates,
- configuration similarity comparison and visualization,
- etc.

## Dataset

The folder structure of can be described as follows:

```txt
<environment>/<system>/<workload>/<run>
```

For `environments` we use only CloudLab and Azure.

For `systems` we have configurations for `PostgreSQL`, `Redis`, and `NGINX`.

For `workloads`, there is not a complete set, however for `PostgreSQL` we have configurations for `mssales`, `TPC-C`, `TPC-H`, and `epinions`. For `Redis` we only run `YCSB-C`, and for `NGINX` we only run a wikipedia serving workload for the top 500 pages, including all media.

The `run` file name prefixes represent the tuning methodology:

- `traditional_` sampling uses `SMAC3` where every configuration only evaluated once.
- `TUNA_` uses the methodology described in our writeup.

There are two tuning runs that are slightly different that are for our ablation studies in the paper:

1. We have our TPC-C tuning run with a gaussian process optimizer which are found in `azure/postgres/tpcc_gp`.
2. We have traditional tuning runs tuning TPC-C, which were run for longer than others, which are found in `azure/postgres/tpcc`, with `long` appended to their file names.

## Schema

Each file represents a single tuning run.

| Suggestion | Config | Worker | Performance |
|---|---|---|---|
| 0 | {...} | 0 | 810.09 |
| 1 | {...} | 0 | 904.34 |
| ... | ... | ... | ... |

The schema is quite simple for the files.

- The `Suggestion` column represents the number of suggestions the configuration tuner has made for this tuning run.
- The `Config` is a string representation of the json object we sent to the worker evaluation node.
- The `Worker` column is a number representing the ID of the worker.

  > Note that these worker IDs are not global; they are only relative within a tuning run, and do not imply that all of these runs were done on the same cluster.

- The `Performance` column meaning depends on the workload being run.

  For `TPC-C`, and `epinions` this is throughput (transactions per second), for `TPC-H` and `mssales` this is runtime for the entire workload, and for the wikipedia workload and `YCSB-C` this is the 95th percentile latency.

## Example Usage

We provide a [`sample.ipynb`](./sample.ipynb) notebook in this folder to show how to read and interact with the workloads.
This notebook includes how to plot the convergence curves, and select the highest performing configuration across all runs.
