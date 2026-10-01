import typer
from rich.console import Console

app = typer.Typer(help="RetryLab: Idempotency fuzzer")
console = Console()

@app.command()
def run(spec: str = typer.Option(..., help="Path to OpenAPI spec")):
    """
    Run the idempotency fuzzer against a target.
    """
    console.print(f"[bold green]Starting fuzzer[/bold green] with spec: {spec}")
    # TODO: Week 4-6 implementation

if __name__ == "__main__":
    app()
