"""CLI entry point for zhipin-geek.

Usage:
    geek login / status / logout
    geek search <keyword> [--city C] [--salary S] [--exp E] [--degree D]
    geek recommend [--page N]
    geek me / applied / interviews
    geek messages [-n N]
    geek unread [-n N]
    geek reply <friendId> "text"
    geek chat-history <friendId> [-n N]
    geek send-resume / request-phone / request-wechat <friendId>
    geek accept <friendId> [--reject]
    geek greet <securityId>
    geek batch-greet <keyword> [-n N] [--city C] [--dry-run]
    geek cities
"""

from __future__ import annotations

import logging

import click

from . import __version__
from .commands import auth, personal, search, social


@click.group()
@click.version_option(version=__version__, prog_name="geek")
@click.option("-v", "--verbose", is_flag=True, help="Enable verbose logging (show request URLs, timing)")
@click.pass_context
def cli(ctx, verbose: bool) -> None:
    """zhipin-geek — BOSS 直聘求职端 CLI"""
    ctx.ensure_object(dict)
    if verbose:
        logging.basicConfig(level=logging.INFO, format="%(name)s %(message)s")
    else:
        logging.basicConfig(level=logging.WARNING)


# ─── Auth commands ───────────────────────────────────────────────────

cli.add_command(auth.login)
cli.add_command(auth.logout)
cli.add_command(auth.status)
cli.add_command(auth.me)

# ─── Search & Browse commands ────────────────────────────────────────

cli.add_command(search.search)
cli.add_command(search.recommend)
cli.add_command(search.detail)
cli.add_command(search.show)
cli.add_command(search.export)
cli.add_command(search.history)
cli.add_command(search.cities)

# ─── Personal Center commands ────────────────────────────────────────

cli.add_command(personal.applied)
cli.add_command(personal.interviews)

# ─── Social / Chat commands ──────────────────────────────────────────

cli.add_command(social.chat_list)
cli.add_command(social.greet)
cli.add_command(social.batch_greet)
cli.add_command(social.messages)
cli.add_command(social.unread_messages)
cli.add_command(social.geek_reply)
cli.add_command(social.chat_history)
cli.add_command(social.send_resume)
cli.add_command(social.request_phone)
cli.add_command(social.request_wechat)
cli.add_command(social.accept_exchange)


if __name__ == "__main__":
    cli()
