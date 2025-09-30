class LeanError(Exception):
    pass


class ReplError(Exception):
    pass


class ReplOOMError(ReplError):
    pass


class NoAvailableReplError(Exception):
    pass
