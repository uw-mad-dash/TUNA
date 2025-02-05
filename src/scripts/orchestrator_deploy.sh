echo $1
echo $2

ssh -p $2 $1 "sudo rm -rf ~/code"
ssh -p $2 $1 "mkdir -p code"
ssh -p $2 $1 "mkdir -p code/results"

pushd ..

scp -P $2 worker_setup.sh $1:.
ssh -p $2 $1 "sudo bash worker_setup.sh"

scp -P $2 ../code/* $1:code
scp -P $2 -r ../code/spaces $1:code
scp -P $2 -r ../code/proto $1:code
scp -P $2 -r ../code/MLOS $1:code
scp -P $2 -r ../code/client $1:code
scp -P $2 -r ../code/benchmarks $1:code

popd