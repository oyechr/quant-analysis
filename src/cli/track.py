"""Tracking picks over time: watchlist, changes, journal."""

from pathlib import Path

import click

from ..data_fetcher import DataFetcher
from ..pipeline import AnalysisOptions
from .common import (
    config_option,
    get_scoring_config,
    workers_option,
)


def _watchlist_file_option():
    from ..tracking import DEFAULT_WATCHLIST

    return click.option(
        "--file",
        "watchlist_file",
        default=DEFAULT_WATCHLIST,
        show_default=True,
        type=click.Path(dir_okay=False, path_type=Path),
        help="Watchlist file.",
    )


def _journal_file_option():
    from ..tracking import DEFAULT_JOURNAL

    return click.option(
        "--journal",
        "journal_file",
        default=DEFAULT_JOURNAL,
        show_default=True,
        type=click.Path(dir_okay=False, path_type=Path),
        help="Decision journal file.",
    )


@click.group()
@_watchlist_file_option()
@click.pass_context
def watchlist(ctx, watchlist_file):
    """Keep a list of tickers to follow, with a thesis and price levels.

    The list lives in watchlist.toml (gitignored; edit it by hand if you
    like). `quant changes` checks it, and `quant screen watchlist` screens it.

    \b
    Examples:
      quant watchlist add EQNR.OL --thesis "Cheap vs peers" --target 450 --stop 380
      quant watchlist add AAPL MSFT
      quant watchlist rm MSFT
      quant watchlist ls
    """
    ctx.obj["watchlist_file"] = watchlist_file


@watchlist.command("add")
@click.argument("tickers", nargs=-1, required=True)
@click.option("--thesis", default=None, help="One line on why you're watching it.")
@click.option("--target", type=float, default=None, help="Target price (listing currency).")
@click.option("--stop", type=float, default=None, help="Stop price (listing currency).")
@click.pass_context
def watchlist_add(ctx, tickers, thesis, target, stop):
    """Add TICKERS, or update the thesis/target/stop of ones already listed."""
    from ..tracking import add_to_watchlist

    path = ctx.obj["watchlist_file"]
    try:
        added, updated = add_to_watchlist(path, tickers, thesis=thesis, target=target, stop=stop)
    except ValueError as e:
        raise click.ClickException(str(e)) from e
    if added:
        click.echo(f"  Added {', '.join(added)} to {path}")
    if updated:
        click.echo(f"  Updated {', '.join(updated)}")


@watchlist.command("rm")
@click.argument("tickers", nargs=-1, required=True)
@click.pass_context
def watchlist_rm(ctx, tickers):
    """Remove TICKERS from the watchlist."""
    from ..tracking import remove_from_watchlist

    path = ctx.obj["watchlist_file"]
    try:
        removed, missing = remove_from_watchlist(path, tickers)
    except ValueError as e:
        raise click.ClickException(str(e)) from e
    if removed:
        click.echo(f"  Removed {', '.join(removed)} from {path}")
    if missing:
        click.echo(f"  Not on the watchlist: {', '.join(missing)}")


@watchlist.command("ls")
@click.pass_context
def watchlist_ls(ctx):
    """List the watchlist with each ticker's last recorded score."""
    from ..tracking import load_history, load_watchlist, render_watchlist

    path = ctx.obj["watchlist_file"]
    try:
        items = load_watchlist(path)
    except ValueError as e:
        raise click.ClickException(str(e)) from e
    if not items:
        click.echo(f"  {path} is empty. Add tickers with: quant watchlist add T --thesis '...'")
        return

    last = {row["ticker"]: row for row in load_history(ctx.obj["output_dir"])}
    click.echo(render_watchlist(path, items, last))


@click.command()
@click.argument("tickers", nargs=-1)
@config_option()
@workers_option()
@_watchlist_file_option()
@click.option(
    "--portfolio",
    "portfolio_file",
    default="portfolio/portfolio.csv",
    show_default=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Holdings to check too (skipped if the file doesn't exist).",
)
@_journal_file_option()
@click.option(
    "--save", is_flag=True, help="Also write <output-dir>/_changes/changes_DATE.md and .json."
)
@click.option(
    "--notify",
    is_flag=True,
    help="Show a Windows notification when something is worth a look (or nothing scored).",
)
@click.option("--json", "as_json", is_flag=True, help="Print the result as JSON.")
@click.pass_context
def changes(
    ctx,
    tickers,
    config_name,
    workers,
    watchlist_file,
    portfolio_file,
    journal_file,
    save,
    notify,
    as_json,
):
    """What moved since the last run: the watchlist and holdings, or TICKERS.

    Rescores each ticker, records it in the score history
    (<output-dir>/_history/scores.csv), and compares it with its latest run
    from an earlier day: score and signal, red flags that appeared or
    cleared, the price move, price against the watchlist target/stop, and
    earnings in the next 14 days. Every report/score/vet/screen run also
    feeds the history.

    Without TICKERS it checks the watchlist, the holdings in --portfolio and
    the tickers with an open thesis in --journal, and lists the theses that
    broke or need a recheck (see `quant journal`).

    --save and --notify are for a daily scheduled run (see the README).

    \b
    Examples:
      quant changes
      quant changes EQNR.OL AAPL
      quant changes --config value
      quant -q changes --save --notify
    """
    import json as _json

    from ..tracking import (
        load_journal,
        load_watchlist,
        render_markdown,
        render_text,
        summary_line,
        track_changes,
    )

    output_dir = ctx.obj["output_dir"]
    try:
        watched = load_watchlist(watchlist_file)
        decisions = load_journal(journal_file)
    except ValueError as e:
        raise click.ClickException(str(e)) from e
    held = _held_tickers(portfolio_file, strict=not tickers)
    open_tickers = [d.ticker for d in decisions if d.is_open]
    if tickers:
        tickers_list = list(dict.fromkeys(t.upper() for t in tickers))
        decisions = [d for d in decisions if d.ticker in tickers_list]
    else:
        tickers_list = list(dict.fromkeys([*watched, *held, *open_tickers]))
    if not tickers_list:
        raise click.ClickException(
            f"No tickers given, {watchlist_file} is empty and there are no holdings in "
            f"{portfolio_file}. Add some with: quant watchlist add T --thesis '...'"
        )

    def progress(ticker, error):
        if not as_json:
            mark = "✗" if error else "✓"
            click.echo(f"  {mark} {ticker}" + (f": {error}" if error else ""), err=True)

    if not as_json:
        click.echo(f"  Checking {len(tickers_list)} ticker(s)...", err=True)
    result = track_changes(
        tickers_list,
        fetcher=DataFetcher(cache_dir=output_dir),
        options=AnalysisOptions(
            period=ctx.obj["period"],
            use_cache=ctx.obj["use_cache"],
            include_context=False,
            scoring_config=get_scoring_config(config_name),
        ),
        watchlist=watched,
        data_dir=output_dir,
        workers=workers,
        progress=progress,
        held=held,
        journal=decisions,
    )
    data = result.to_dict()
    if as_json:
        click.echo(_json.dumps(data, indent=2, default=str))
    else:
        click.echo(render_text(data))

    digest = None
    if save:
        out_dir = Path(output_dir) / "_changes"
        out_dir.mkdir(parents=True, exist_ok=True)
        digest = out_dir / f"changes_{data['date']}.md"
        digest.write_text(render_markdown(data), encoding="utf-8")
        digest.with_suffix(".json").write_text(
            _json.dumps(data, indent=2, default=str), encoding="utf-8"
        )
        click.echo(f"  Saved: {digest}, {digest.with_suffix('.json')}", err=True)
    if notify:
        from ..utils.notify import toast

        line = summary_line(data)
        if line is None:
            click.echo("  Nothing worth a notification.", err=True)
        elif not toast(f"quant changes {data['date']}", line, digest):
            click.echo("  ! Notification not shown (see the log; Windows only).", err=True)


def _held_tickers(portfolio_file: Path, strict: bool) -> list[str]:
    """
    Tickers in the portfolio file; none if it doesn't exist. An unreadable
    file stops the run when the holdings are what it checks (strict), and
    only warns when they just mark the tickers given.
    """
    from ..portfolio import load_portfolio

    if not portfolio_file.exists():
        return []
    try:
        holdings, _ = load_portfolio(portfolio_file)
    except (ValueError, OSError) as e:
        if strict:
            raise click.ClickException(f"{portfolio_file}: {e}") from e
        click.echo(f"  ! Holdings not read ({portfolio_file}: {e})", err=True)
        return []
    return [h.ticker for h in holdings]


# ==================== Journal ====================


def _date_type():
    return click.DateTime(formats=["%Y-%m-%d"])


@click.group()
@_journal_file_option()
@click.pass_context
def journal(ctx, journal_file):
    """Record why you buy and sell, and check the theses later.

    Each buy or add records a thesis and what would prove it wrong: a stop,
    a minimum score, a review date, or a free-text --exit-if. The score,
    signal and red flags at the time are saved with it (default preset, the
    one the daily `quant changes` run uses). `quant changes`
    then checks every open thesis against the latest scores, and
    `journal lookback` shows how each decision did against its benchmark.

    The journal lives in portfolio/journal.toml (gitignored; edit it by
    hand if you like). A sell closes the ticker's open buys and adds.

    \b
    Examples:
      quant journal add EQNR.OL --thesis "Cheap vs peers" --stop 380 --min-score 50
      quant journal add EQNR.OL --action sell --thesis "Capex up again"
      quant journal ls
      quant journal lookback --since 2026-01-01
    """
    ctx.obj["journal_file"] = journal_file


@journal.command("add")
@click.argument("ticker")
@click.option(
    "--action",
    type=click.Choice(["buy", "add", "trim", "sell"], case_sensitive=False),
    default="buy",
    show_default=True,
)
@click.option(
    "--thesis",
    default=None,
    help="Why: the thesis for a buy or add (required; taken from the watchlist if "
    "listed there), the reason for a trim or sell.",
)
@click.option("--exit-if", default=None, help="What would prove the thesis wrong, in words.")
@click.option("--price", type=float, default=None, help="Your price (default: the last close).")
@click.option("--shares", type=float, default=None, help="Shares bought or sold.")
@click.option("--stop", type=float, default=None, help="Broken below this price.")
@click.option("--target", type=float, default=None, help="Recheck at this price.")
@click.option("--min-score", type=float, default=None, help="Broken below this score.")
@click.option("--review-by", type=_date_type(), default=None, help="Recheck by this date.")
@click.option(
    "--date",
    "day",
    type=_date_type(),
    default=None,
    help="Decision date (default today). An earlier date takes its snapshot from the history.",
)
@click.pass_context
def journal_add(
    ctx,
    ticker,
    action,
    thesis,
    exit_if,
    price,
    shares,
    stop,
    target,
    min_score,
    review_by,
    day,
):
    """Record a decision on TICKER, with a snapshot of its score."""
    from datetime import date

    from ..tracking import (
        DEFAULT_WATCHLIST,
        OPENING,
        Decision,
        add_decision,
        check_thesis,
        load_history,
        load_watchlist,
        snapshot_row,
    )

    ticker = ticker.upper()
    action = action.lower()
    today = date.today()
    decided = day.date() if day else today
    if action in OPENING:
        try:
            watched = load_watchlist(Path(DEFAULT_WATCHLIST)).get(ticker)
        except ValueError as e:
            raise click.ClickException(str(e)) from e
        if watched is not None:
            thesis = thesis or watched.thesis
            target = target if target is not None else watched.target
            stop = stop if stop is not None else watched.stop
        if not thesis:
            raise click.ClickException(
                f"A {action} needs a thesis: --thesis 'why, and what would prove it wrong'"
            )

    decision = Decision(
        ticker=ticker,
        date=decided,
        action=action,
        thesis=thesis,
        exit_if=exit_if,
        price=price,
        shares=shares,
        stop=stop,
        target=target,
        min_score=min_score,
        review_by=review_by.date() if review_by else None,
    )
    # The default preset only: the daily `changes` run keeps those rows fresh
    preset = get_scoring_config("default").name
    row = _score_now(ctx, ticker) if decided == today else None
    if row is None:
        row = snapshot_row(load_history(ctx.obj["output_dir"], ticker, preset), decided)
    decision.take_snapshot(row)
    if decision.preset is None:
        decision.preset = preset

    path = ctx.obj["journal_file"]
    try:
        closed = add_decision(path, decision)
    except ValueError as e:
        raise click.ClickException(str(e)) from e
    snapshot = (
        f"score {decision.score:.0f} {decision.signal}, price {decision.price:,.2f}"
        if decision.score is not None and decision.price is not None
        else "no score snapshot"
    )
    click.echo(f"  Recorded {action} {ticker} on {decided.isoformat()} ({snapshot}) in {path}")
    for d in closed:
        click.echo(f"  Closed the {d.action} of {d.date.isoformat()}")
    if decision.is_open and row is not None:
        broken, _ = check_thesis(decision, row, today)
        if broken:
            click.echo(
                f"  ! Broken from the start: {'; '.join(broken)}. "
                f"Fix the criteria in {path} if that's not what you meant.",
                err=True,
            )


def _score_now(ctx, ticker: str):
    """Score the ticker and record it in the history; None (with a warning) if that fails."""
    from ..pipeline import analyze_ticker
    from ..tracking import history_row
    from .common import record_history

    output_dir = ctx.obj["output_dir"]
    options = AnalysisOptions(
        period=ctx.obj["period"],
        use_cache=ctx.obj["use_cache"],
        include_context=False,
        scoring_config=get_scoring_config("default"),
    )
    try:
        bundle = analyze_ticker(ticker, DataFetcher(cache_dir=output_dir), options)
    except Exception as e:
        click.echo(f"  ! Couldn't score {ticker} ({e}); using the score history", err=True)
        return None
    row = history_row(bundle.report, bundle.scoring, "journal")
    if row is None:
        click.echo(f"  ! No score for {ticker}; using the score history", err=True)
        return None
    record_history(output_dir, [row])
    return row


@journal.command("ls")
@click.option("--all", "show_all", is_flag=True, help="Also list closed and trim/sell decisions.")
@click.option("--json", "as_json", is_flag=True, help="Print the checks as JSON.")
@click.pass_context
def journal_ls(ctx, show_all, as_json):
    """Open theses, checked against the latest score history.

    Uses the scores already recorded (run `quant changes` first for fresh
    ones). Broken: below the stop, under the minimum score, or a Sell signal or
    high red flag new since the decision. Check: target or review date
    reached, the score down 10+ points since the decision, or no score in a week.
    """
    import json as _json

    from ..tracking import check_journal, load_history, load_journal, render_journal

    path = ctx.obj["journal_file"]
    try:
        decisions = load_journal(path)
    except ValueError as e:
        raise click.ClickException(str(e)) from e
    if not decisions:
        click.echo(f"  {path} is empty. Record a decision with: quant journal add T --thesis '...'")
        return
    checks = check_journal(decisions, load_history(ctx.obj["output_dir"]))
    if as_json:
        click.echo(_json.dumps([c.to_dict() for c in checks], indent=2, default=str))
        return
    others = [d for d in decisions if not d.is_open] if show_all else []
    click.echo(render_journal(path, checks, others))


@journal.command("lookback")
@click.option("--since", type=_date_type(), default=None, help="Only decisions from this date.")
@click.option("--json", "as_json", is_flag=True, help="Print the outcomes as JSON.")
@click.pass_context
def journal_lookback(ctx, since, as_json):
    """How each decision did against its home benchmark.

    From the close on the decision date to the close when the position was
    sold, or today. A buy or add is a good call when it beat the benchmark,
    a trim or sell when the stock lagged it afterwards. Grouped by the
    signal at the time, to see whether following it helped.
    """
    import json as _json
    import math
    from datetime import date

    from ..backtest.engine import history_period
    from ..markets import benchmark_for
    from ..tracking import load_journal, look_back, render_look_back

    path = ctx.obj["journal_file"]
    try:
        decisions = load_journal(path)
    except ValueError as e:
        raise click.ClickException(str(e)) from e
    start = since.date() if since else None
    chosen = [d for d in decisions if start is None or d.date >= start]
    if not chosen:
        click.echo(f"  No decisions in {path}" + (f" since {start}" if start else ""))
        return

    years = max(1, math.ceil((date.today() - min(d.date for d in chosen)).days / 365))
    period = history_period(years)
    fetcher = DataFetcher(cache_dir=ctx.obj["output_dir"])
    cache: dict = {}

    def closes(symbol):
        if symbol not in cache:
            try:
                frame = fetcher.fetch_ticker(symbol, period=period, use_cache=ctx.obj["use_cache"])
                cache[symbol] = frame["Close"] if "Close" in frame.columns else None
            except Exception as e:
                click.echo(f"  ! No prices for {symbol}: {e}", err=True)
                cache[symbol] = None
        return cache[symbol]

    outcomes = look_back(chosen, closes, benchmark_for)
    if as_json:
        click.echo(_json.dumps([o.to_dict() for o in outcomes], indent=2, default=str))
    else:
        click.echo(render_look_back(outcomes))
