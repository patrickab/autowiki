import subprocess
import sys
import tomllib
from pathlib import Path


def run_synto(vault_path: Path) -> None:
    config_path = vault_path / "synto.toml"
    if not config_path.is_file():
        raise RuntimeError(f"Missing {config_path}; initialize the vault with `uv run synto init {vault_path} --existing`")

    executable = Path(sys.executable).with_name("synto")
    if not executable.is_file():
        raise RuntimeError(f"Synto executable not found next to Python: {executable}")

    with config_path.open("rb") as file:
        config = tomllib.load(file)
    command = [str(executable), "run", "--vault", str(vault_path)]
    if config.get("pipeline", {}).get("auto_approve", False):
        command.append("--auto-approve")

    subprocess.run(
        command,
        check=True,
    )
