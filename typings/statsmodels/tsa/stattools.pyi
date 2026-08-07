from numpy import float64
from numpy.typing import NDArray

type AdfResult = tuple[float, float, int, int, dict[str, float], float]
type TestValues = tuple[float, float, float, float]
type TestMap = dict[str, TestValues]
type LagResult = tuple[TestMap, tuple[None, None, None]]

def adfuller(
    x: NDArray[float64],
    maxlag: int | None = ...,
    regression: str = ...,
    autolag: str | None = ...,
    store: bool = ...,
    regresults: bool = ...,
) -> AdfResult: ...

def grangercausalitytests(
    x: NDArray[float64],
    maxlag: int | list[int],
    addconst: bool = ...,
    verbose: bool | None = ...,
) -> dict[int, LagResult]: ...
