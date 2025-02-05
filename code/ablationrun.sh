for i in {1..25}
do
    python3 adjusted_distributed.py $2 $i $1
    python3 no_model_distributed.py $2 $i $1
done