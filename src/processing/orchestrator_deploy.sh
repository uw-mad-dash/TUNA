echo $1
echo $2

# set up the conda environment
scp -P $2 requirements.txt $1:.
scp -P $2 *.sh $1:.

ssh -p $2 $1 "bash ./install_conda.sh"
ssh -p $2 $1 "export PATH=\$PATH:~/miniconda3/bin ; source ~/miniconda3/etc/profile.d/conda.sh ; conda init ; cd src/MLOS ; make"
ssh -p $2 $1 "export PATH=\$PATH:~/miniconda3/bin ; source ~/miniconda3/etc/profile.d/conda.sh ; conda init ; conda create -n mlos python=3.11 -y ; conda activate mlos"
ssh -p $2 $1 "export PATH=\$PATH:~/miniconda3/bin ; source ~/miniconda3/etc/profile.d/conda.sh ; conda activate mlos ; bash ./node_setup.sh"

ssh -p $2 $1 "sudo rm -rf ~/src"
ssh -p $2 $1 "mkdir -p src"
ssh -p $2 $1 "mkdir -p src/results"

pushd ..

# set up the environment
scp -P $2 worker_setup.sh $1:.
ssh -p $2 $1 "sudo bash worker_setup.sh"

# copy the source code to the remote machine
scp -P $2 ../src/* $1:src
scp -P $2 -r ../src/spaces $1:src
scp -P $2 -r ../src/proto $1:src
scp -P $2 -r ../src/MLOS $1:src
scp -P $2 -r ../src/executors $1:src
scp -P $2 -r ../src/client $1:src
scp -P $2 -r ../src/benchmarks $1:src

popd