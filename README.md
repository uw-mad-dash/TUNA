# TUNA: Tuning Unstable and Noisy Cloud Applications

Summary

## Source Code Structure

TUNA uses [MLOS](https://github.com/microsoft/MLOS) as it's base tuning framework, and implements a custom scheduling and sampling policy on top of it, and then selects tuners from those offered. TUNA also uses [Nautilus](https://dl.acm.org/doi/pdf/10.1145/3650203.3663336) to manage and deploy the execution environment. The code here is a fork of a private library that will be released soon.

- `src`
  - `benchmarks`
  - `client`
  - `executors`
  - `legacy_proxy`
  - `nautilus`
  - `processing`
  - `proto`
  - `spaces`
  - `workloads`
  - `wrk_scripts`


## Environment

## Run Experiments

## Usage Examples