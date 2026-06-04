"""Entry points for the laptop-side machine vision client."""

from machine_vision_client.heat_algorithm import main as run_heat_algorithm


def main() -> None:
    run_heat_algorithm()


if __name__ == "__main__":
    main()
