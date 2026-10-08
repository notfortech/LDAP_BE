"""Engine error types. All are configuration or input errors: the engine
never raises for a legitimate response pattern, including an empty one."""


class EngineError(Exception):
    """Base class for every error this package raises."""


class ConfigError(EngineError):
    """The configuration on disk is missing, malformed, or internally
    inconsistent. Raised at load time, never during scoring, so a bad
    config cannot reach a live assessment."""


class ResponseError(EngineError):
    """A submitted response references an unknown option. Unknown item
    ids are ignored rather than rejected -- an item withdrawn from a set
    must not invalidate a result already in flight -- but an option
    outside the scale is a client defect and is surfaced."""
