#!/bin/bash

# move the requiremenst over
parallel-scp -h $1 requirements.txt .

pushd ..

cat $1

# stop and remove the previous containers
parallel-ssh -h $1 "sudo docker kill dbms"
parallel-ssh -h $1 "sudo docker rm dbms"
parallel-ssh -h $1 "sudo pkill python3"

# remove old files
parallel-ssh -h $1 "sudo rm -rf ./nautilus"
parallel-scp -r -h $1 nautilus .
parallel-ssh -h $1 "sudo rm -rf /opt/nautilus"
parallel-ssh -h $1 "sudo cp -r nautilus /opt/nautilus"

# remake folders
parallel-ssh -h $1 "sudo mkdir -p /opt/proxy"
parallel-ssh -h $1 "sudo mkdir -p /opt/output"

# Install the docker images
parallel-ssh -h $1 "sudo tmux kill-session -t install"
parallel-ssh -h $1 "sudo tmux new-session -d -s install \"export PATH=\$PATH:~/miniconda3/bin ; . ~/miniconda3/etc/profile.d/conda.sh ; conda activate p311 ; cd /opt/nautilus && python3 deploy.py start head deploy=cloudlab +deploy/instance_type=$2\" ; sudo tmux set-option remain-on-exit on"
read -p "Press enter to continue once docker image has been built"

# copy the files over
for files in proxy proto client benchmarks
do
    parallel-scp -r -h $1 $files .
    parallel-ssh -h $1 "sudo rm -rf /opt/proxy/$files"
    parallel-ssh -h $1 "sudo cp -r $files /opt/proxy"
done
parallel-ssh -h $1 "sudo cp -r /opt/proxy/proxy/* /opt/proxy"
parallel-ssh -h $1 "sudo rm -rf /opt/proxy/nautilus"
parallel-ssh -h $1 "sudo mkdir /opt/proxy/nautilus"
parallel-ssh -h $1 "sudo cp -r nautilus/* /opt/proxy/"
parallel-ssh -h $1 "cd /opt/nautilus && sudo mkdir logs"

# give permissions for global folders
parallel-ssh -h $1 "sudo chmod -R 777 /opt/proxy/"
parallel-ssh -h $1 "sudo chmod -R 777 /opt/nautilus/"

# start the proxy
parallel-ssh -h $1 "tmux kill-session -t proxy"
parallel-ssh -h $1 "tmux new-session -d -s proxy \"export PATH=\$PATH:~/miniconda3/bin ; . ~/miniconda3/etc/profile.d/conda.sh ; conda activate p311 ; cd /opt/proxy && python3 evaluation_server.py --dir /datadrive\" ; tmux set-option remain-on-exit on"

popd

