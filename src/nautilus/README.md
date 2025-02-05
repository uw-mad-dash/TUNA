# Nautilus

Nautilus's purpose is to streamline the evaluation of DBMS configurations. In other words, it provides a platform that enables measuring the performance of a DBMS configuration under different workloads and hardware configurations.

Currently Nautilus supports two DBMSs (i.e. PostgreSQL, MySQL) and two benchmark suites (i.e. [YCSB](https://github.com/brianfrankcooper/YCSB), [BenchBase](https://github.com/cmu-db/benchbase)). Yet, its architecture allows the easy integration of any other DBMS / benchmark suite.

## Deploying

Nautilus has been tested in CloudLab infrastructure. While it currently supports `c220g5` instance types, there is provision in the design to support more instance types.

The easiest way to deploy Nautlius is to use Cloudlab's `nautilus-ray` profile ([link](https://www.cloudlab.us/p/bb9f3a4050fbbdd36e0635e40c1fbe53820f0d42)).

## Running (single node)

If it is the first time that you connect to node, run the following to access `docker` without root access:

```bash
sudo usermod -aG docker $USER
newgrp
```

Then, navigate to `/opt/nautilus` directory. Nautilus' files should be located there. To activate the conda environment, run:

```bash
source activate_env.sh
```

To deploy Nautilus, run the following:

```bash
python3 deploy.py start head deploy=cloudlab +deploy/instance_type=c220g5
```

This should run without any issues. In this case, you can check the worker output for more details by running:

```bash
docker logs worker
```

You should see something like the following:

```
2024-04-02 01:39:24,189	INFO usage_lib.py:449 -- Usage stats collection is enabled by default without user confirmation because this terminal is detected to be non-interactive. To disable this, add `--disable-usage-stats` to the command that starts the cluster, or run the following command: `ray disable-usage-stats` before starting the cluster. See https://docs.ray.io/en/master/cluster/usage-stats.html for more details.
2024-04-02 01:39:24,189	INFO scripts.py:744 -- Local node IP: 172.18.0.2
2024-04-02 01:39:28,327	SUCC scripts.py:781 -- --------------------
2024-04-02 01:39:28,328	SUCC scripts.py:782 -- Ray runtime started.
2024-04-02 01:39:28,328	SUCC scripts.py:783 -- --------------------
2024-04-02 01:39:28,329	INFO scripts.py:785 -- Next steps
2024-04-02 01:39:28,329	INFO scripts.py:788 -- To add another node to this Ray cluster, run
2024-04-02 01:39:28,330	INFO scripts.py:791 --   ray start --address='172.18.0.2:6379'
2024-04-02 01:39:28,330	INFO scripts.py:800 -- To connect to this Ray cluster:
2024-04-02 01:39:28,330	INFO scripts.py:802 -- import ray
2024-04-02 01:39:28,331	INFO scripts.py:803 -- ray.init()
2024-04-02 01:39:28,331	INFO scripts.py:815 -- To submit a Ray job using the Ray Jobs CLI:
2024-04-02 01:39:28,331	INFO scripts.py:816 --   RAY_ADDRESS='http://172.18.0.2:8265' ray job submit --working-dir . -- python my_script.py
2024-04-02 01:39:28,331	INFO scripts.py:825 -- See https://docs.ray.io/en/latest/cluster/running-applications/job-submission/index.html
2024-04-02 01:39:28,331	INFO scripts.py:829 -- for more information on submitting Ray jobs to the Ray cluster.
2024-04-02 01:39:28,331	INFO scripts.py:834 -- To terminate the Ray runtime, run
2024-04-02 01:39:28,332	INFO scripts.py:835 --   ray stop
2024-04-02 01:39:28,332	INFO scripts.py:838 -- To view the status of the cluster, use
2024-04-02 01:39:28,332	INFO scripts.py:839 --   ray status
2024-04-02 01:39:28,332	INFO scripts.py:843 -- To monitor and debug Ray, view the dashboard at
2024-04-02 01:39:28,333	INFO scripts.py:844 --   172.18.0.2:8265
2024-04-02 01:39:28,333	INFO scripts.py:851 -- If connection to the dashboard fails, check your firewall settings and network configuration.
2024-04-02 01:39:28,334	INFO scripts.py:952 -- --block
2024-04-02 01:39:28,334	INFO scripts.py:953 -- This command will now block forever until terminated by a signal.
2024-04-02 01:39:28,334	INFO scripts.py:956 -- Running subprocesses are monitored and a message will be printed if any of them terminate unexpectedly. Subprocesses exit with SIGTERM will be treated as graceful, thus NOT reported.
```

This means that Nautilus has been successfully deployed, and is currently awaiting for jobs.

An example script that submits a single job can be found in `run-task.py`. In particular, it instructs Nautilus to run PostgreSQL v16.1 (with the default configuration), using the TPC-C benchmark (provided by BenchBase).

To run this script, execute the following command (derived from the previous output):

```bash
RAY_ADDRESS='http://172.18.0.2:8265' ray job submit --working-dir . --no-wait -- python3 run-task.py
```

You should see something like this:

```bash
Job submission server address: http://172.18.0.2:8265
2024-04-01 20:39:41,857	INFO dashboard_sdk.py:338 -- Uploading package gcs://_ray_pkg_5e51b9a824521de2.zip.
2024-04-01 20:39:41,858	INFO packaging.py:530 -- Creating a file package for local directory '.'.

-------------------------------------------------------
Job 'raysubmit_H5A9Z6U6MyVSQj9L' submitted successfully
-------------------------------------------------------

Next steps
  Query the logs of the job:
    ray job logs raysubmit_H5A9Z6U6MyVSQj9L
  Query the status of the job:
    ray job status raysubmit_H5A9Z6U6MyVSQj9L
  Request the job to be stopped:
    ray job stop raysubmit_H5A9Z6U6MyVSQj9L
```

To track the progress of the job, by running the above commands.


Finally, to stop Nautilus, we run the following:

```bash
python3 deploy.py stop head profile=cloudlab
```
