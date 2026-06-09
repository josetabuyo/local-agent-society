import click
from cli.commands.system import status, start_cmd, stop_cmd, logs, install, uninstall, update
from cli.commands.speak import speak
from cli.commands.agents import agent, agents_list, widget
from cli.commands.ports import ports
from cli.commands.voices import voices
from cli.commands.queue import queue
from cli.commands.boarding import boarding


@click.group()
def cli():
    """Local Agent Society — CLI"""


cli.add_command(status)
cli.add_command(start_cmd, name="start")
cli.add_command(stop_cmd, name="stop")
cli.add_command(logs)
cli.add_command(install)
cli.add_command(uninstall)
cli.add_command(update)
cli.add_command(speak)
cli.add_command(agents_list, name="agents")
cli.add_command(agent)
cli.add_command(widget)
cli.add_command(ports)
cli.add_command(voices)
cli.add_command(queue)
cli.add_command(boarding)
