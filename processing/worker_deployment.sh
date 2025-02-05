pushd ..

cat $1

parallel-ssh -h $1 "sudo docker kill dbms"
parallel-ssh -h $1 "sudo docker rm dbms"
parallel-ssh -h $1 "sudo pkill python3.11"


parallel-ssh -h $1 "sudo rm -rf ./nautilus"
parallel-scp -r -h $1 nautilus .
parallel-ssh -h $1 "sudo rm -rf /opt/nautilus"
parallel-ssh -h $1 "sudo cp -r nautilus /opt/nautilus"

parallel-ssh -h $1 "sudo mkdir -p /opt/proxy"
parallel-ssh -h $1 "sudo mkdir -p /opt/output"

parallel-ssh -h $1 "sudo tmux kill-session -t install"
parallel-ssh -h $1 "export PATH=\$PATH:/opt/anaconda3/bin ; . /home/azureuser/miniconda3/etc/profile.d/conda.sh ; conda activate worker ; sudo tmux new-session -d -s install \"cd /opt/nautilus && python3.11 -m pip install six && python3.11 deploy.py start head deploy=cloudlab +deploy/instance_type=$2\" ; sudo tmux set-option remain-on-exit on"


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

parallel-ssh -h $1 "sudo chmod -R 777 /opt/proxy/"
parallel-ssh -h $1 "sudo chmod -R 777 /opt/nautilus/"

parallel-ssh -h $1 "tmux kill-session -t proxy"
parallel-ssh -h $1 "export PATH=\$PATH:/opt/anaconda3/bin ; . /home/azureuser/miniconda3/etc/profile.d/conda.sh ; conda activate worker ; tmux new-session -d -s proxy \"cd /opt/proxy && python3.11 evaluation_server_v2.py --dir /datadrive\" ; tmux set-option remain-on-exit on"

popd

