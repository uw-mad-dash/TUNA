parallel-ssh -t 0 -h $1 "\
sudo apt-get update -y ;\
sudo apt install python3.11-dev -y ;\
sudo python3.11 -m pip install hydra-core --upgrade ;\
sudo python3.11 -m pip install grpcio ;\
sudo python3.11 -m pip install --upgrade google-api-python-client ;\
sudo python3.11 -m pip install pandas ;\
sudo python3.11 -m pip install scipy ;\
sudo python3.11 -m pip install -U scikit-learn ;\
sudo python3.11 -m pip install pyyaml ;\
sudo python3.11 -m pip install ConfigSpace ;\
sudo python3.11 -m pip install psutil ;\
sudo python3.11 -m pip install regex ;\
sudo python3.11 -m pip install grpcio grpcio-tools ;\
sudo python3.11 -m pip install jpype1 ;\
sudo python3.11 -m pip install dacite ;\
sudo python3.11 -m pip install pympler ;\
sudo python3.11 -m pip install jaydebeapi ;\
sudo python3.11 -m pip install setuptools==69.5.1 ;\
sudo python3.11 -m pip install netifaces ;\
sudo python3.11 -m pip install ray[defualt]==2.9.3 ;\
sudo python3.11 -m pip uninstall -y attr ;\
sudo python3.11 -m pip install omegaconf>=2.2,<2.4 ;\
sudo python3.11 -m pip install six ;\
sudo python3.11 -m pip install attrs ;\
"