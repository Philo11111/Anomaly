"""python -m anomaly [run|backtest|probe]"""

from __future__ import annotations

import sys


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "run"
    if command in {"run", "serve"}:
        from anomaly.app import main as run

        run()
        return
    if command == "backtest":
        from anomaly.backtest import main as backtest

        raise SystemExit(backtest())
    if command == "probe":
        from anomaly.probe import main as probe

        raise SystemExit(probe())
    print("usage: python -m anomaly [run|backtest|probe]", file=sys.stderr)
    raise SystemExit(2)


if __name__ == "__main__":
    main()
