#!/usr/bin/env python3
"""
Entrypoint oficial para executar o bot Telegram 24/7 em nuvem.
"""

from main_production import main


if __name__ == "__main__":
    raise SystemExit(main())
