import sys

from websensors_flow_rag.cli import main_process


def main():
    if len(sys.argv) < 2 or sys.argv[1] != "process":
        print("Uso: python -m websensors_flow_rag process --file ARQUIVO --project PROJETO --config YAML", file=sys.stderr)
        raise SystemExit(2)
    main_process(sys.argv[2:])


if __name__ == "__main__":
    main()
