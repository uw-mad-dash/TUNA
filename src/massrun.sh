for i in {1..10}
do
    parallel-ssh -h hosts.azure.port "sudo docker kill dbms"
    parallel-ssh -h hosts.azure.port "sudo docker rm dbms"
    parallel-ssh -h hosts.azure.port "sudo docker kill worker"
    parallel-ssh -h hosts.azure.port "sudo docker rm worker"

    parallel-ssh -h hosts.azure.port "sudo rm -rf /datadrive/data/*"


    parallel-ssh -h hosts.azure.port "sudo tmux kill-session -t install"
    parallel-ssh -h hosts.azure.port "export PATH=\$PATH:/opt/anaconda3/bin ; . /home/azureuser/miniconda3/etc/profile.d/conda.sh ; conda activate worker ; sudo tmux new-session -d -s install \"cd /opt/nautilus && python3.11 deploy.py start head deploy=cloudlab +deploy/instance_type=$3\" ; sudo tmux set-option remain-on-exit on"
    sleep 180
    parallel-ssh -h hosts.azure.port "tmux kill-session -t proxy"
    parallel-ssh -h hosts.azure.port "export PATH=\$PATH:/opt/anaconda3/bin ; . /home/azureuser/miniconda3/etc/profile.d/conda.sh ; conda activate worker ; tmux new-session -d -s proxy \"cd /opt/proxy && python3.11 evaluation_server_v2.py --dir /datadrive\" ; tmux set-option remain-on-exit on"
    sleep 180

    python3 adjusted_distributed.py $2 $i $1

done

parallel-ssh -h hosts.azure.port "sudo docker kill dbms"
parallel-ssh -h hosts.azure.port "sudo docker rm dbms"
parallel-ssh -h hosts.azure.port "kill worker"
parallel-ssh -h hosts.azure.port "sudo docker rm worker"
parallel-ssh -h hosts.azure.port "sudo rm -rf /datadrive/data/*"

parallel-ssh -h hosts.azure.port "sudo tmux kill-session -t install"
parallel-ssh -h hosts.azure.port "export PATH=\$PATH:/opt/anaconda3/bin ; . /home/azureuser/miniconda3/etc/profile.d/conda.sh ; conda activate worker ; sudo tmux new-session -d -s install \"cd /opt/nautilus && python3.11 deploy.py start head deploy=cloudlab +deploy/instance_type=$3\" ; sudo tmux set-option remain-on-exit on"
sleep 180
parallel-ssh -h hosts.azure.port "tmux kill-session -t proxy"
parallel-ssh -h hosts.azure.port "export PATH=\$PATH:/opt/anaconda3/bin ; . /home/azureuser/miniconda3/etc/profile.d/conda.sh ; conda activate worker ; tmux new-session -d -s proxy \"cd /opt/proxy && python3.11 evaluation_server_v2.py --dir /datadrive\" ; tmux set-option remain-on-exit on"
sleep 180
python3 parallel.py $2 $i $1