# Configuration Dataset

This folder contains the configurations which we found during the tuning runs presented in the paper, TUNA.
At a high level, configurations which were tuned in the south central us region are under the `azure` folder, configurations tuned in central us are in the `azure_centralus` folder, and the configurations found in CloudLab are under `cloudlab`.
For azure, we use exclusively `D8s_v5` nodes, and for CloudLab we use exclusively `c220g5` nodes.
Deploying these in environments that are not representative of their tuning environment can have unpredictable results.

# Dataset

The folder structure of can be described as follows:
`<environment>/<system>/<workload>/<run>`

For environments we use only CloudLab and Azure.
For systems we have configurations for `PostgreSQL`, `Redis`, and `NGINX`.
For workloads, there is not a complete set, however for `PostgreSQL` we have configurations for `mssales`, `TPC-C`, `TPC-H`, and `epinions`. For `Redis` we only run `YCSB-C`, and for `NGINX` we only run a wikipedia serving workload for the top 500 pages, including all media.

The file names represent the tuning methodology. Traditional sampling uses `SMAC3` where every configuration only evaluated once. `TUNA` uses the methodology described in our writeup.

There are two tuning runs that are slightly different that are for our ablation studies in the paper.
First, we have our TPC-C tuning run with a gaussian process optimizer which are found in `azure/postgres/tpcc_gp`.
Second, we have traditional tuning runs tuning TPC-C, which were run for longer than others, which are found in `azure/postgres/tpcc`, with `long` appended to their file names.

## Schema

| Suggestion | Config | Worker | Performance |
|---|---|---|---|
| 0 | {...} | 0 | 810.09 |
| 1 | {...} | 0 | 904.34 |
| ... | ... | ... | ... |

The schema is quite simple for the files.
The suggestion column represents the number of suggestions the configuration tuner has made for this tuning run. The configuration is a string representation of the json object we sent to the worker evaluation node. The worker number is the ID of the worker. Note that these worker IDs are not global; they are only relative within a tuning run, and do not imply that all of these runs were done on the same cluster.
Finally the performance column meaning depends on the workload being run. For `TPC-C`, and `epinions` this is throughput (transactions per second), for `TPC-H` and `mssales` this is runtime for the entire workload, and for the wikipedia workload and `YCSB-C` this is the 95th percentile latency.

## Example Usage

We provide an example notebook in this folder to show how to read and interact with the workloads. This notebook includes how to plot the convergence curves, and select the highest performing configuration across all runs.