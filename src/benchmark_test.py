import time

from benchmarks import Benchmark

canary = Benchmark.Canary()
canary.start()

time.sleep(10)
print("Timer Stopped")

can_res = canary.stop()

print(can_res)
