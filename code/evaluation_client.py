import json
from abc import ABC
from typing import Any

import grpc
from proto import message_pb2, message_pb2_grpc


class Evaluator(ABC):
    def evaluate(self, config: dict[str, Any], dbms_info: dict[str, str] = None, benchmark_info: dict[str, str] = None, timeout=2400) -> Any:
        pass

    def collect_queries(self, config: dict[str, Any], dbms_info: dict[str, str] = None, benchmark_info: dict[str, str] = None, timeout=2400) -> Any:
        pass

    def evaluate_loss(self, config: dict[str, Any], dbms_info: dict[str, str] = None, benchmark_info: dict[str, str] = None, loss_fn: message_pb2.LossFunction = message_pb2.LossFunction.LOSS_UNSPECIFIED, timeout=2400) -> Any:
        pass

    def ping(self) -> None:
        pass


class EmptyEvaluatorClient(Evaluator):
    def __init__(
        self,
    ):
        pass

    def evaluate(
        self,
        config: dict[str, Any],
        dbms_info: dict[str, str] = None,
        benchmark_info: dict[str, str] = None,
        timeout=2400,
    ) -> Any:
        return message_pb2.Performanace(
            throughput=1,
            goodput=1,
            latencyp50=1,
            latencyp95=1,
            latencyp99=1,
            runtime=1,
            metrics="{}",
        )

    def ping(self) -> None:
        pass


class EvaluatorClient(Evaluator):
    def __init__(
        self,
        host: str,
        dbms_info: dict[str, str],
        benchmark_info: dict[str, str],
        metrics: bool = False,
    ):
        self.host = host
        self.channel = grpc.insecure_channel(host)
        self.stub = message_pb2_grpc.DistributedWorkerStub(self.channel)

        self.dbms_info = dbms_info
        self.benchmark_info = benchmark_info
        self.metrics = metrics

        print(dbms_info)
        print(benchmark_info)

    def __del__(self) -> None:
        self.channel.close()

    def evaluate(
        self,
        config: dict[str, Any],
        dbms_info: dict[str, str] = None,
        benchmark_info: dict[str, str] = None,
        timeout=2400,
    ) -> Any:
        print("Starting Evaluate")

        if dbms_info is None:
            dbms_info = self.dbms_info
        if benchmark_info is None:
            benchmark_info = self.benchmark_info

        result = self.stub.EvaluateConfig(
            message_pb2.Config(
                dbms_info=json.dumps(dbms_info | {"config": config}),
                benchmark_info=json.dumps(benchmark_info),
                metrics=self.metrics,
            ),
            timeout=timeout,
        )

        return result

    def collect_queries(
        self,
        config: dict[str, Any],
        dbms_info: dict[str, str] = None,
        benchmark_info: dict[str, str] = None,
        timeout=2400,
    ) -> Any:
        print("Starting Query Collection")

        if dbms_info is None:
            dbms_info = self.dbms_info
        if benchmark_info is None:
            benchmark_info = self.benchmark_info

        result = self.stub.CollectQueries(
            message_pb2.Config(
                dbms_info=json.dumps(dbms_info | {"config": config}),
                benchmark_info=json.dumps(benchmark_info),
                metrics=self.metrics,
            ),
            timeout=timeout,
        )

        return message_pb2.Empty()

    def evaluate_loss(
        self,
        config: dict[str, Any],
        dbms_info: dict[str, str] = None,
        benchmark_info: dict[str, str] = None,
        loss_fn: message_pb2.LossFunction = message_pb2.LossFunction.LOSS_UNSPECIFIED,
        timeout=2400,
    ) -> Any:
        print("Starting Loss Collection")

        if dbms_info is None:
            dbms_info = self.dbms_info
        if benchmark_info is None:
            benchmark_info = self.benchmark_info

        result = self.stub.EvaluateLoss(
            message_pb2.LossConfig(
                dbms_info=json.dumps(dbms_info | {"config": config}),
                benchmark_info=json.dumps(benchmark_info),
                loss=loss_fn
            ),
            timeout=timeout,
        )

        return result

    def ping(self) -> None:
        try:
            response = self.stub.Ping(message_pb2.Empty())
            print("Ping Successful")
        except Exception as e:
            print(f"Ping Failed: {e}")
