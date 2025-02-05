# TUNA: Tuning Unstable and Noisy Cloud Applications

Summary

## Source Code Structure

TUNA uses [MLOS](https://github.com/microsoft/MLOS) as it's base tuning framework, and implements a custom scheduling and sampling policy on top of it, and then selects tuners from those offered. TUNA also uses [Nautilus](https://dl.acm.org/doi/pdf/10.1145/3650203.3663336) to manage and deploy the execution environment. The code here is a fork of a private library that will be released soon.

- `src`
  - `benchmarks`: Metric collection scripts
  - `client`: Orchestrator side scheduling policies
  - `nautilus`: Nautilus dependency. See [Paper](https://dl.acm.org/doi/pdf/10.1145/3650203.3663336).
  - `proto`: gRPC communication definition files
  - `proxy`: A worker sided proxy to forward incoming messages to nautilus
    - `executors`: worker side server to listen for incoming gRPC requests
    - `nautilus`: stub files for proper linting
  - `processing`: deployment and management scripts
  - `spaces`
    - `benchmark`: Workload definitions for nautilus
    - `dbms`: Database definitions for nautilus
    - `experiment`: Files defining how benchmarks, dbms, knobs, and params are combined
    - `knobs`: List of knob definitions
    - `params`: Machine characteristics


## Environment

## Run Experiments

## Usage Examples