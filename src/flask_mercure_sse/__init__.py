import importlib

# this trick ensures that the server module __main__ will be the first loaded
# module when called as `python -m flask_mercure_sse.server` to ensure monkey
# patching is performed first
def __getattr__(name):
    if name == "server":
        return importlib.import_module(".server", __name__)
    ext = importlib.import_module(".ext", __name__)
    return getattr(ext, name)