"""Print english, japanese or absent: the language the installed Net de
Bomberman shows, by its browser name (bombinstall keeps the two in step).

    python3 -m bomb.state DEVICE
"""
import sys

from bomb import bombinstall

if __name__ == "__main__":
    print(bombinstall.state(sys.argv[1]))
