from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class LossFunction(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = []
    LOSS_UNSPECIFIED: _ClassVar[LossFunction]
    LOSS_L1: _ClassVar[LossFunction]
    LOSS_L2: _ClassVar[LossFunction]
    LOSS_L1_Level: _ClassVar[LossFunction]
    LOSS_L2_Level: _ClassVar[LossFunction]
LOSS_UNSPECIFIED: LossFunction
LOSS_L1: LossFunction
LOSS_L2: LossFunction
LOSS_L1_Level: LossFunction
LOSS_L2_Level: LossFunction

class Config(_message.Message):
    __slots__ = ["dbms_info", "benchmark_info", "metrics", "benchmarks"]
    DBMS_INFO_FIELD_NUMBER: _ClassVar[int]
    BENCHMARK_INFO_FIELD_NUMBER: _ClassVar[int]
    METRICS_FIELD_NUMBER: _ClassVar[int]
    BENCHMARKS_FIELD_NUMBER: _ClassVar[int]
    dbms_info: str
    benchmark_info: str
    metrics: bool
    benchmarks: bool
    def __init__(self, dbms_info: _Optional[str] = ..., benchmark_info: _Optional[str] = ..., metrics: bool = ..., benchmarks: bool = ...) -> None: ...

class LossConfig(_message.Message):
    __slots__ = ["dbms_info", "benchmark_info", "loss"]
    DBMS_INFO_FIELD_NUMBER: _ClassVar[int]
    BENCHMARK_INFO_FIELD_NUMBER: _ClassVar[int]
    LOSS_FIELD_NUMBER: _ClassVar[int]
    dbms_info: str
    benchmark_info: str
    loss: LossFunction
    def __init__(self, dbms_info: _Optional[str] = ..., benchmark_info: _Optional[str] = ..., loss: _Optional[_Union[LossFunction, str]] = ...) -> None: ...

class Performanace(_message.Message):
    __slots__ = ["throughput", "goodput", "latencyp50", "latencyp95", "latencyp99", "runtime", "metrics"]
    THROUGHPUT_FIELD_NUMBER: _ClassVar[int]
    GOODPUT_FIELD_NUMBER: _ClassVar[int]
    LATENCYP50_FIELD_NUMBER: _ClassVar[int]
    LATENCYP95_FIELD_NUMBER: _ClassVar[int]
    LATENCYP99_FIELD_NUMBER: _ClassVar[int]
    RUNTIME_FIELD_NUMBER: _ClassVar[int]
    METRICS_FIELD_NUMBER: _ClassVar[int]
    throughput: float
    goodput: float
    latencyp50: float
    latencyp95: float
    latencyp99: float
    runtime: float
    metrics: str
    def __init__(self, throughput: _Optional[float] = ..., goodput: _Optional[float] = ..., latencyp50: _Optional[float] = ..., latencyp95: _Optional[float] = ..., latencyp99: _Optional[float] = ..., runtime: _Optional[float] = ..., metrics: _Optional[str] = ...) -> None: ...

class Loss(_message.Message):
    __slots__ = ["loss"]
    LOSS_FIELD_NUMBER: _ClassVar[int]
    loss: float
    def __init__(self, loss: _Optional[float] = ...) -> None: ...

class Empty(_message.Message):
    __slots__ = []
    def __init__(self) -> None: ...
