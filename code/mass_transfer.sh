for i in {0..15}
do
    python3 parallel_transfer.py spaces/experiment/pg16.1-tpcc-4to8.json $(($1+$i)) hosts.azure spaces/baseconfig/raw_data/best_8c32m_$i.json
done