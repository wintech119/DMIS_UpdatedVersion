from importlib import import_module

__all__ = ["contract_services", "services"]


def __getattr__(name: str):
    if name in {"contract_services", "services"}:
        module = import_module(".contract_services", __name__)
        globals()["contract_services"] = module
        globals()["services"] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
