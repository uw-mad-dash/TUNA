for i in $(seq 1 10);
do
	wrk -t 12 -c 400 -d 300s -s report.lua  http://localhost >> test3.txt
done
