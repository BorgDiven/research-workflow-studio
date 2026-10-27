#!/usr/bin/env python3
"""Absolute-path launcher, so MCP does not depend on its client's cwd."""
from rws.__main__ import main
if __name__ == '__main__':
    main()
