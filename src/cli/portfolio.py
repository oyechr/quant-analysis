"""Your holdings: import-portfolio, review."""

from pathlib import Path

import click

from ..data_fetcher import DataFetcher
from ..pipeline import AnalysisOptions
from .common import (
    config_option,
    get_scoring_config,
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
@click.pass_context
def review(ctx, portfolio_file, config_name, workers, base, as_json, save):
    """Review the holdings in a portfolio file: Exit / Review / Trim / Hold / Add.

    Runs `vet` on every holding, values them in --base, and compares each
    weight to a risk-parity (inverse-volatility) target. The rules:

    \b
      Exit   a Sell or Strong Sell signal
      Review a high-severity red flag with a Hold/Buy signal: look into it
      Trim   weight >= 1.5x target (and 2+ points over), or moves with a
             larger holding (daily-return correlation >= 0.80)
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
    import json as _json

    from ..portfolio import load_portfolio, render_markdown, render_text, review_portfolio

    output_dir = ctx.obj["output_dir"]
    holdings, unmapped = load_portfolio(Path(portfolio_file))
    if not holdings:
        raise click.ClickException(f"No holdings with a ticker in {portfolio_file}")

    def progress(ticker, error):
        if not as_json:
            mark = "✗" if error else "✓"
            click.echo(f"  {mark} {ticker}" + (f": {error}" if error else ""), err=True)

    if not as_json:
        click.echo(f"  Reviewing {len(holdings)} holdings...", err=True)
    result = review_portfolio(
        holdings,
        fetcher=DataFetcher(cache_dir=output_dir),
        options=AnalysisOptions(
            period=ctx.obj["period"],
            use_cache=ctx.obj["use_cache"],
            include_context=False,
            scoring_config=get_scoring_config(config_name),
        ),
        base_currency=base.upper(),
        workers=workers,
        data_dir=output_dir,
        progress=progress,
    )
    result.unmapped = unmapped

    data = result.to_dict()
    if as_json:
        click.echo(_json.dumps(data, indent=2, default=str))
    else:
        click.echo(render_text(data))

    if save:
        out_dir = Path(portfolio_file).parent
        (out_dir / "review.json").write_text(
            _json.dumps(data, indent=2, default=str), encoding="utf-8"
        )
        (out_dir / "review.md").write_text(render_markdown(data), encoding="utf-8")
        click.echo(f"  Saved: {out_dir / 'review.json'}, {out_dir / 'review.md'}", err=True)
