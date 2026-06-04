"""Back-compat shim.

The heat algorithm was decomposed into the package's module slots:
  - RGB source        -> video/visible_stream.py
  - thermal source    -> video/thermal_stream.py
  - classification    -> vision/pipeline.py
  - drawing / HUD     -> ui/debug_viewer.py
  - web feeds         -> ui/web_server.py
  - orchestration     -> main.py

See docs/superpowers/specs/2026-06-04-heat-algorithm-integration-design.md.
This module only re-exports `main` so older entry points keep working.
"""

from machine_vision_client.main import main

__all__ = ["main"]


if __name__ == "__main__":
    main()
