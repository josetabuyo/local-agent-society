import shutil

import click
from cli.commands.system import status, start_cmd, stop_cmd, restart_cmd, logs, install, uninstall, update
from cli.commands.speak import speak
from cli.commands.agents import agent, agents_list, link, widget, widgets_all
from cli.commands.ports import ports
from cli.commands.voices import voices
from cli.commands.queue import queue
from cli.commands.boarding import boarding
from cli.commands.completion import completion
from cli.commands.shell_init import shell_init
from cli.commands.vocab import vocab_cmd
from cli.commands.bridge import bridge, claude_cmd, claude_relay_cmd, codex_cmd, shell_cmd
from cli.commands.detach import detach_cmd


class LasGroup(click.Group):
    """`las <any command…>`: when the first word is not a `las` subcommand but a
    program on PATH, run it connected to LAS in this terminal — a session of
    this folder's agent, like `las claude` or `las codex` (docs/adr/0006):
    `las pulpo agent run`. The command speaks the ADR 0006 stdio contract."""

    def get_command(self, ctx, name):
        found = super().get_command(ctx, name)
        if found is not None or not shutil.which(name):
            return found
        from cli.commands.bridge import run_connected

        @click.command(name, context_settings={"ignore_unknown_options": True, "allow_extra_args": True, "help_option_names": []})
        @click.argument("args", nargs=-1, type=click.UNPROCESSED)
        def connected(args):
            run_connected([name, *args])
        return connected


@click.group(cls=LasGroup)
def cli():
    """Local Agent Society — CLI.

    If the current directory has a .las-agent.json, you are a local agent of this society. Load the
    `/las-agent` skill before doing anything else — it covers how to speak
    (`las speak`), how to talk to other agents on this machine or another
    one (`las agent send`), how the widget works, and what's expected of
    you as a member of the society. Don't rediscover any of this from the
    command tree; it's already documented there.
    """


cli.add_command(status)
cli.add_command(start_cmd, name="start")
cli.add_command(stop_cmd, name="stop")
cli.add_command(restart_cmd, name="restart")
cli.add_command(logs)
cli.add_command(install)
cli.add_command(uninstall)
cli.add_command(update)
cli.add_command(speak)
cli.add_command(agents_list, name="agents")
cli.add_command(agent)
cli.add_command(widget)
cli.add_command(widgets_all, name="widgets")
cli.add_command(link)
cli.add_command(ports)
cli.add_command(voices)
cli.add_command(queue)
cli.add_command(boarding)
cli.add_command(completion)
cli.add_command(bridge)
cli.add_command(claude_cmd, name="claude")
cli.add_command(claude_relay_cmd, name="claudeRelay")
cli.add_command(codex_cmd, name="codex")
cli.add_command(shell_cmd, name="shell")
cli.add_command(detach_cmd, name="detach")
cli.add_command(shell_init, name="shell-init")
cli.add_command(vocab_cmd, name="vocab")
