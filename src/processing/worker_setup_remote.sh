#!/bin/bash
parallel-scp -h $1 requirements.txt .
parallel-scp -h $1 *.sh .

parallel-ssh -t 0 -h $1 "bash ./install_conda.sh"
parallel-ssh -t 0 -h $1 "export PATH=\$PATH:~/miniconda3/bin ; source ~/miniconda3/etc/profile.d/conda.sh ; conda init ; conda create -n p311 python=3.11 -y ; conda activate p311"
parallel-ssh -t 0 -h $1 "export PATH=\$PATH:~/miniconda3/bin ; source ~/miniconda3/etc/profile.d/conda.sh ; conda activate p311 ; bash ./node_setup.sh"
