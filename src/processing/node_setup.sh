#!/bin/bash

# Install python packages
pip3 install -r requirements.txt
pip3 install hydra-core --upgrade

# Add Docker's official GPG key:
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

# Add the repository to Apt sources:
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Resize Disk
(echo d ; echo 3 ; echo n ; echo 3 ; echo "" ; echo "" ; echo y ; echo w) | sudo fdisk /dev/sda
sudo resize2fs /dev/sda3

# Install docker package after docker is installed
pip3 install docker

# Install Java 21
wget -O /tmp/jdk-21.deb https://download.oracle.com/java/21/latest/jdk-21_linux-x64_bin.deb \
    && sudo dpkg -i /tmp/jdk-21.deb \
    && rm -f /tmp/jdk-21.deb

# Make sure /datadrive exists
sudo mkdir -p /datadrive
sudo chmod -R 777 /datadrive

sudo apt-get install -y fio stress-ng linux-tools-common linux-tools-generic linux-tools-`uname -r` 
sudo mkdir -p /opt/mlc ; sudo chmod -R 777 /opt/mlc
wget https://downloadmirror.intel.com/793041/mlc_v3.11.tgz ; tar -xvf mlc_v3.11.tgz -C /opt/mlc
