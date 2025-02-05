
def apply_jaydebeapi_patch():
    """ Monkey patching

    JPype does not handle Java "boxed" types (e.g. java.lang.Long) correctly
    when converting to Python types. This is a workaround to fix that.
    More info
    - https://github.com/jpype-project/jpype/issues/1098
    - https://stackoverflow.com/questions/26899595/jpype-and-jaydebeapi-returns-jpype-jclass-java-lang-long
    """
    from jaydebeapi import _DEFAULT_CONVERTERS, _java_to_py, _to_decimal, _to_double, _to_int, _to_boolean

    def _explicit_cast(method, cast_type):
        def cast(*args, **kwargs):
            v = method(*args, **kwargs)
            return cast_type(v) if v is not None else None
        return cast

    _to_double_fix = _explicit_cast(_to_double, float)
    _to_int_fix = _explicit_cast(_to_int, int)
    _to_boolean_fix = _explicit_cast(_to_boolean, bool)
    _to_decimal_fix = _explicit_cast(_to_decimal, float)
    _to_long_fix = _explicit_cast(_java_to_py('longValue'), int)

    _DEFAULT_CONVERTERS.update({
        'DECIMAL': _to_decimal_fix,
        'NUMERIC': _to_decimal_fix,
        'DOUBLE': _to_double_fix,
        'FLOAT': _to_double_fix,
        'TINYINT': _to_int_fix,
        'INTEGER': _to_int_fix,
        'SMALLINT': _to_int_fix,
        'BOOLEAN': _to_boolean_fix,
        'BIT': _to_boolean_fix,
        # The following two are not in the default converters
        'BIGINT': _to_long_fix,
        'REAL': _to_double_fix,
    })
