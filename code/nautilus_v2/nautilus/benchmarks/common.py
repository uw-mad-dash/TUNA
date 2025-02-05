from enum import Enum, auto

class AutoNameEnum(Enum):
    def _generate_next_value_(name, start, count, last_values): # pylint: disable=no-self-argument
        return name

class IsolationLevel(AutoNameEnum):
    TRANSACTION_NONE             = auto()
    TRANSACTION_READ_UNCOMMITTED = auto()
    TRANSACTION_REPEATABLE_READ  = auto()
    TRANSACTION_READ_COMMITTED   = auto()
    TRANSACTION_SERIALIZABLE     = auto()
