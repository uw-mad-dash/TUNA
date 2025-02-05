class DBMSInfo:
    name: str
    # (knob, value) configuration dictionary
    config: (
        dict[str, int | float | str] | None
    )  # pylint: disable=unsubscriptable-object
    version: str | None
