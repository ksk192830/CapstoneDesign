"""Unified app: car control + heat-algorithm vision in separate OpenCV windows."""

from machine_vision_client.heat_algorithm import main as run_unified


def main() -> None:
    run_unified()


if __name__ == "__main__":
    main()
