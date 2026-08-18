import sys
from typing import Final, final


VERSION: Final = "v16"


@final
class BootstrapObserver:
    __slots__: tuple[str, ...] = ("active", "later_imports", "network_attempts")
    active: bool
    later_imports: int
    network_attempts: int

    def __init__(self) -> None:
        self.active = True
        self.later_imports = 0
        self.network_attempts = 0

    def audit(self, event: str, arguments: tuple[str | int | float | bytes | None, ...]) -> None:
        if not self.active:
            return
        if event.startswith("socket."):
            self.network_attempts += 1
        if event == "import" and arguments and isinstance(arguments[0], str):
            name = arguments[0]
            version = name.removeprefix("src.v").split(".", maxsplit=1)[0]
            if name.startswith("src.v") and version.isdigit() and int(version) >= 17:
                self.later_imports += 1

    def disable(self) -> None:
        self.active = False


BOOTSTRAP_OBSERVER: Final[BootstrapObserver | None] = (
    BootstrapObserver()
    if len(sys.argv) > 1 and sys.argv[1].endswith("acceptance")
    else None
)
if BOOTSTRAP_OBSERVER is not None:
    sys.addaudithook(BOOTSTRAP_OBSERVER.audit)
