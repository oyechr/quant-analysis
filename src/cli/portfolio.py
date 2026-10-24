"""Your holdings: import-portfolio, review, rebalance."""

from pathlib import Path

import click

from ..data_fetcher import DataFetcher
from ..pipeline import AnalysisOptions
from .common import (
    config_option,
    get_scoring_config,
    record_history,
    workers_option,
)


@click.command("import-portfolio")
@click.argument("exports", nargs=-1, required=True, type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--map",
    "map_path",
    default="portfolio/tickers.csv",
    show_default=True,
    help="CSV mapping Nordnet names to Yahoo tickers (columns: name,ticker).",
)
@click.option(
    "--out",
    "out_path",
    default="portfolio/portfolio.csv",
    show_default=True,
    help="Combined portfolio file to write.",
)
@click.option(
    "--label",
    "labels",
    multiple=True,
    help="Account label, e.g. --label 12345678=ASK (default: the account number).",
)
@click.option("--verify", is_flag=True, help="Look up each ticker on Yahoo and show its name.")
@click.pass_context
def import_portfolio(ctx, exports, map_path, out_path, labels, verify):
    """Combine Nordnet holdings exports into one portfolio file.

    EXPORTS are Nordnet holdings exports, one per account ("Beholdningstabell
    eksport, kontono. <number>, <date>.csv", or the older
    "aksjelister_konto-<number>_<date>.csv"). Names are mapped
    to Yahoo tickers with --map; unmapped names are listed so you can add
    them and rerun. Keep real holdings in the gitignored portfolio/ folder.

    \b
    Example:
      quant import-portfolio "~/Downloads/Beholdningstabell eksport*.csv" --label 12345678=ASK --verify
    """
    from ..portfolio import (
        account_from_filename,
        combine_holdings,
        load_ticker_map,
        write_portfolio,
    )

    label_map = dict(label.split("=", 1) for label in labels if "=" in label)

    def account_for(path: str) -> str | None:
        number = account_from_filename(Path(path))
        return label_map.get(number) if number else None

    holdings, unmapped = combine_holdings(
        [(Path(p), account_for(p)) for p in exports], load_ticker_map(Path(map_path))
    )
    write_portfolio(holdings, Path(out_path))
    click.echo(f"  Wrote {len(holdings)} holdings from {len(exports)} account(s) to {out_path}")
    if unmapped:
        click.echo(f"  No ticker for {len(unmapped)} name(s); add them to {map_path}:")
        for name in unmapped:
            click.echo(f"    {name}")

    if verify:
        from ..utils.fx import major_currency

        fetcher = DataFetcher(cache_dir=ctx.obj["output_dir"])
        width = max([6, *(len(t) for t in holdings["ticker"])])
        click.echo(f"\n  {'Ticker':<{width}} {'Nordnet name':<32} {'Yahoo name':<32} Currency")
        for row in holdings.drop_duplicates("ticker").itertuples():
            if not row.ticker:
                continue
            info = fetcher.get_ticker_info(row.ticker)
            yahoo_ccy = info.get("currency") or "?"
            same = major_currency(yahoo_ccy)[0] == major_currency(row.currency)[0]
            click.echo(
                f"  {row.ticker:<{width}} {row.name[:32]:<32} {str(info.get('name') or 'NOT FOUND')[:32]:<32} "
                f"{row.currency}/{yahoo_ccy}{'' if same else '  <- check'}"
            )


TARGETS_OPTION = click.option(
    "--targets",
    "targets_file",
    default="portfolio/targets.toml",
    show_default=True,
    type=click.Path(dir_okay=False),
    help="Limits and per-ticker targets (optional; defaults apply without it).",
)


@click.command()
@click.argument(
    "portfolio_file",
    default="portfolio/portfolio.csv",
    type=click.Path(exists=True, dir_okay=False),
)
@config_option()
@workers_option()
@click.option("--base", default="NOK", show_default=True, help="Currency to value holdings in.")
@click.option("--json", "as_json", is_flag=True, help="Print the result as JSON.")
@click.option(
    "--save", is_flag=True, help="Also write review.json and review.md next to the portfolio file."
)
@TARGETS_OPTION
@click.pass_context
def review(ctx, portfolio_file, config_name, workers, base, as_json, save, targets_file):
    """Review the holdings in a portfolio file: Exit / Review / Trim / Hold / Add.

    Runs `vet` on every holding, values them in --base, and compares each
    weight to its target: equal risk contribution (every holding the same
    share of portfolio risk), within the limits in --targets. The rules:

    \b
      Exit   a Sell or Strong Sell signal
      Review a high-severity red flag with a Hold/Buy signal: look into it
      Trim   weight >= 1.5x target (and 2+ points over), or moves with a
             larger holding (weekly-return correlation >= 0.80)
      Add    vet verdict Look deeper, below target, no overlap
      Hold   everything else (funds are only ever Trim or Hold)
      Check  no price data (usually a wrong ticker in the map)

    PORTFOLIO_FILE comes from `quant import-portfolio` (default:
    portfolio/portfolio.csv). The first run fetches every holding and its
    peers, so it takes a few minutes; later runs use the cache.

    \b
    Examples:
      quant review
      quant review --config value --save
      quant review portfolio/portfolio.csv --json
    """
    from ..portfolio import render_markdown, render_text

    result, _ = _run_review(
        ctx, portfolio_file, config_name, workers, base, targets_file, quiet=as_json
    )
    data = result.to_dict()
    click.echo(_to_json(data) if as_json else render_text(data))
    if save:
        _save(Path(portfolio_file).parent, "review", data, render_markdown(data))


@click.command()
@click.argument(
    "portfolio_file",
    default="portfolio/portfolio.csv",
    type=click.Path(exists=True, dir_okay=False),
)
@click.option(
    "--cash",
    type=float,
    default=0.0,
    show_default=True,
    help="Cash to invest, in --base (on top of what the sales raise).",
)
@click.option(
    "--candidates",
    default="",
    help="New names to consider: 'watchlist' (watchlist.toml) or tickers, comma-separated.",
)
@TARGETS_OPTION
@config_option()
@workers_option()
@click.option("--base", default="NOK", show_default=True, help="Currency to value holdings in.")
@click.option("--json", "as_json", is_flag=True, help="Print the proposal as JSON.")
@click.option(
    "--save",
    is_flag=True,
    help="Also write rebalance.json and rebalance.md next to the portfolio file.",
)
@click.pass_context
def rebalance(
    ctx, portfolio_file, cash, candidates, targets_file, config_name, workers, base, as_json, save
):
    """Propose trades: sell Exits, trim, add, and buy new candidates.

    Runs `review`, then turns its actions into trades, in this order:

    
      1. Exit: sell everything
      2. Review / Check: no trade
      3. Trim, or above the position limit: sell down to target or cap
      4. Sector above its limit: sell its lowest-scoring stocks
      5. Add: buy up to target, from --cash plus what the sales raised
      6. Candidates with a Look deeper verdict that don't move with a
         holding: best score first, at most max_new, at the median target
      7. Whole shares; trades under min_trade are dropped

    Sales come from ASK first; AF sales at a gain show the estimated tax.
    Buys of non-EEA companies are AF only. Limits (max_position,
    max_sector, cash_reserve, min_trade, max_new) come from --targets.

    
    Examples:
      quant rebalance
      quant rebalance --cash 50000 --candidates watchlist
      quant rebalance --candidates EQNR.OL,AAPL --save
    """
    from ..portfolio import (
        rebalance_portfolio,
        render_proposal_markdown,
        render_proposal_text,
    )

    result, targets = _run_review(
        ctx, portfolio_file, config_name, workers, base, targets_file, quiet=as_json
    )
    tickers = _candidate_tickers(candidates)
    if tickers and not as_json:
        click.echo(f"  Vetting {len(tickers)} candidate(s)...", err=True)
    proposal = rebalance_portfolio(
        result,
        tickers,
        targets,
        cash=cash,
        fetcher=DataFetcher(cache_dir=ctx.obj["output_dir"]),
        options=_options(ctx, config_name),
        workers=workers,
        data_dir=ctx.obj["output_dir"],
        progress=None if as_json else _progress,
    )
    data = proposal.to_dict()
    click.echo(_to_json(data) if as_json else render_proposal_text(data))
    if save:
        _save(Path(portfolio_file).parent, "rebalance", data, render_proposal_markdown(data))


def _run_review(ctx, portfolio_file, config_name, workers, base, targets_file, quiet):
    """Load the portfolio and the targets file, and review the holdings."""
    from ..portfolio import load_portfolio, load_targets, review_portfolio

    holdings, unmapped = load_portfolio(Path(portfolio_file))
    try:
        targets = load_targets(Path(targets_file))
    except (ValueError, OSError) as e:
        raise click.ClickException(f"{targets_file}: {e}") from e
    if not holdings:
        raise click.ClickException(f"No holdings with a ticker in {portfolio_file}")

    if not quiet:
        click.echo(f"  Reviewing {len(holdings)} holdings...", err=True)
    output_dir = ctx.obj["output_dir"]
    result = review_portfolio(
        holdings,
        fetcher=DataFetcher(cache_dir=output_dir),
        options=_options(ctx, config_name),
        base_currency=base.upper(),
        workers=workers,
        data_dir=output_dir,
        progress=None if quiet else _progress,
        targets=targets,
    )
    result.unmapped = unmapped
    record_history(output_dir, result.history_rows)
    return result, targets


def _candidate_tickers(candidates: str) -> list[str]:
    """'watchlist' -> the watchlist's tickers; otherwise a comma-separated list."""
    from ..tracking import DEFAULT_WATCHLIST, load_watchlist

    tickers: list[str] = []
    for part in (p.strip() for p in candidates.split(",")):
        if part.lower() == "watchlist":
            try:
                tickers += list(load_watchlist(Path(DEFAULT_WATCHLIST)))
            except ValueError as e:
                raise click.ClickException(str(e)) from e
        elif part:
            tickers.append(part.upper())
    return list(dict.fromkeys(tickers))


def _options(ctx, config_name) -> AnalysisOptions:
    return AnalysisOptions(
        period=ctx.obj["period"],
        use_cache=ctx.obj["use_cache"],
        include_context=False,
        scoring_config=get_scoring_config(config_name),
    )


def _progress(ticker, error):
    mark = "✗" if error else "✓"
    click.echo(f"  {mark} {ticker}" + (f": {error}" if error else ""), err=True)


def _to_json(data) -> str:
    import json

    return json.dumps(data, indent=2, default=str)


def _save(out_dir: Path, name: str, data, markdown: str) -> None:
    (out_dir / f"{name}.json").write_text(_to_json(data), encoding="utf-8")
    (out_dir / f"{name}.md").write_text(markdown, encoding="utf-8")
    click.echo(f"  Saved: {out_dir / (name + '.json')}, {out_dir / (name + '.md')}", err=True)
