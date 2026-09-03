"""Punto de entrada del ejecutable.

PyInstaller necesita un script suelto al que apuntar; este solo delega en el
mismo `main()` que usa `python -m autoedit`.
"""

import multiprocessing
import sys

from autoedit.__main__ import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
