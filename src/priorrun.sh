for i in {1..10}
do
    for n in 0 0.05 0.10
    do
        python3 parallel_prior.py $2 $i $1 $n
    done
done