"""命令行入口"""

import sys
from .interfaces.cli import main

if __name__ == "__main__":
    sys.exit(main())
