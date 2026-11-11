__all__ = ["TrueConfBot", "TrueConfChatOps"]


def __getattr__(name):
    if name == "TrueConfBot":
        from .bot import TrueConfBot
        return TrueConfBot
    if name == "TrueConfChatOps":
        from .chatops import TrueConfChatOps
        return TrueConfChatOps
    raise AttributeError(name)
