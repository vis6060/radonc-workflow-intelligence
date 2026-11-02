"""Fail-closed placeholder for separately authorized future live evaluation."""


def run_live_batch(*, explicitly_authorized: bool = False) -> None:
    if not explicitly_authorized:
        raise PermissionError("live model evaluation is disabled by default")
    raise NotImplementedError("M7A does not implement or invoke live model evaluation")
