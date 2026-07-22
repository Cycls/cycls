"""cycls.Image — fluent immutable dict builder for container build config.

Image is a plain `dict` subclass with chainable builder methods. Because it
IS a dict, it spreads natively via `**image` into any decorator's kwargs, or
it can be passed as `image=...` and the factory merges it in the same way.
No helpers, no _to_kwargs(), no conflict scaffolding — Python's kwargs
protocol does the work.
"""


class Image(dict):
    def _with(self, **updates):
        return Image({**self, **updates})

    def pip(self, *pkgs):
        return self._with(pip=[*self.get("pip", []), *pkgs])

    def apt(self, *pkgs):
        return self._with(apt=[*self.get("apt", []), *pkgs])

    def run(self, cmd):
        return self._with(run_commands=[*self.get("run_commands", []), cmd])

    def copy(self, src, dst=None):
        return self._with(copy={**self.get("copy", {}), src: dst or src})

    def rebuild(self):
        """Force a full Docker rebuild (disable cache)."""
        return self._with(force_rebuild=True)
