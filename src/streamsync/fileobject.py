import pathlib

class fileobject:
    def __init__(self, path: str):
        p = pathlib.Path(path)
        self.path = path
        self.name = p.name
        self.stem = p.stem
        self.directory = str(p.parent)

    def __str__(self):
        return f"fileobject: {self.path}"

    def __repr__(self):
        return f"{self.path}"
