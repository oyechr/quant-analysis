"""
Fundamental Analysis Module
Analyzes financial statements and calculates fundamental metrics
"""

import logging
from typing import Any, Dict, List, Optional

import pandas as pd

from ..config import AnalysisConfig, get_config
from ..utils.dataframe_utils import safe_get_dataframe_value
from ..utils.financial import calculate_cagr, calculate_growth_rate, safe_divide

logger = logging.getLogger(__name__)


class FundamentalAnalyzer:
    """
    Analyzes fundamental financial data and calculates key metrics

    Handles:
    - Growth rates (Revenue, Earnings, FCF)
    - Profitability margins
    - Efficiency ratios
    - Quality scores (Altman Z, Piotroski F)
    - DuPont ROE decomposition
    """

    def __init__(
        self,
        ticker_info: Dict[str, Any],
        fundamentals: Optional[Dict[str, pd.DataFrame]] = None,
        price_data: Optional[pd.DataFrame] = None,
        config: Optional[AnalysisConfig] = None,
    ):
        """
        Initialize analyzer with financial data

        Args:
            ticker_info: Dictionary from yfinance ticker.info
            fundamentals: Dictionary with income_stmt, balance_sheet, cash_flow DataFrames
            price_data: Historical price data for market-based calculations
            config: Analysis configuration (uses global defaults if not provided)
        """
        self.info = ticker_info
        self.fundamentals = fundamentals or {}
        self.price_data = price_data
        self.config = config or get_config()

        # Extract financial statements
        self.income_stmt_q = self.fundamentals.get("income_stmt_quarterly")
        self.income_stmt_a = self.fundamentals.get("income_stmt_annual")
        self.balance_sheet_q = self.fundamentals.get("balance_sheet_quarterly")
        self.balance_sheet_a = self.fundamentals.get("balance_sheet_annual")
        self.cash_flow_q = self.fundamentals.get("cash_flow_quarterly")
        self.cash_flow_a = self.fundamentals.get("cash_flow_annual")

    # ==================== Helper Methods ====================

    def _get_value(
        self, df: Optional[pd.DataFrame], row_name: str, col_index: int = 0
    ) -> Optional[float]:
        """Safely extract value from financial statement DataFrame"""
        return safe_get_dataframe_value(df, row_name, col_index)

    def _calculate_growth_rate(
        self, current: Optional[float], previous: Optional[float]
    ) -> Optional[float]:
        """Calculate percentage growth rate"""
        return calculate_growth_rate(current, previous)

    def _safe_divide(
        self, numerator: Optional[float], denominator: Optional[float]
    ) -> Optional[float]:
        """Safely divide two numbers"""
        return safe_divide(numerator, denominator)

    # ==================== Growth Rates ====================

    def calculate_growth_rates(self) -> Dict[str, Any]:
        """
        Calculate revenue, earnings, and FCF growth rates for 1Y, 3Y, 5Y

        Returns:
            Dictionary with growth metrics
        """
        growth = {"revenue": {}, "earnings": {}, "fcf": {}}

        if self.income_stmt_a is not None and not self.income_stmt_a.empty:
            # Revenue growth
            revenue_current = self._get_value(self.income_stmt_a, "Total Revenue", 0)
            revenue_1y = self._get_value(self.income_stmt_a, "Total Revenue", 1)
            revenue_3y = self._get_value(self.income_stmt_a, "Total Revenue", 3)
            revenue_5y = self._get_value(self.income_stmt_a, "Total Revenue", 4)

            growth["revenue"]["1y"] = self._calculate_growth_rate(revenue_current, revenue_1y)
            growth["revenue"]["3y_cagr"] = self._calculate_cagr(revenue_current, revenue_3y, 3)
            growth["revenue"]["5y_cagr"] = self._calculate_cagr(revenue_current, revenue_5y, 5)

            # Earnings growth (Net Income)
            earnings_current = self._get_value(self.income_stmt_a, "Net Income", 0)
            earnings_1y = self._get_value(self.income_stmt_a, "Net Income", 1)
            earnings_3y = self._get_value(self.income_stmt_a, "Net Income", 3)
            earnings_5y = self._get_value(self.income_stmt_a, "Net Income", 4)

            growth["earnings"]["1y"] = self._calculate_growth_rate(earnings_current, earnings_1y)
            growth["earnings"]["3y_cagr"] = self._calculate_cagr(earnings_current, earnings_3y, 3)
            growth["earnings"]["5y_cagr"] = self._calculate_cagr(earnings_current, earnings_5y, 5)

        if self.cash_flow_a is not None and not self.cash_flow_a.empty:
            # FCF growth - try direct field first, then calculate
            # Define OCF field name variants upfront for all fallback calculations
            ocf_field_names = [
                "Operating Cash Flow",
                "Cash Flowsfromusedin Operating Activities Direct",
                "Total Cash From Operating Activities",
                "Net Cash Provided By Operating Activities",
            ]

            fcf_current = self._get_value(self.cash_flow_a, "Free Cash Flow", 0)
            fcf_1y = self._get_value(self.cash_flow_a, "Free Cash Flow", 1)
            fcf_3y = self._get_value(self.cash_flow_a, "Free Cash Flow", 3)

            # If FCF not available directly, calculate from OCF - CapEx
            if fcf_current is None:
                ocf_current = None
                for field_name in ocf_field_names:
                    ocf_current = self._get_value(self.cash_flow_a, field_name, 0)
                    if ocf_current is not None:
                        break

                capex_current = self._get_value(self.cash_flow_a, "Capital Expenditure", 0)
                fcf_current = (
                    ocf_current + capex_current if ocf_current and capex_current else None
                )  # CapEx is negative

            if fcf_1y is None:
                ocf_1y = None
                for field_name in ocf_field_names:
                    ocf_1y = self._get_value(self.cash_flow_a, field_name, 1)
                    if ocf_1y is not None:
                        break
                capex_1y = self._get_value(self.cash_flow_a, "Capital Expenditure", 1)
                fcf_1y = ocf_1y + capex_1y if ocf_1y and capex_1y else None

            if fcf_3y is None:
                ocf_3y = None
                for field_name in ocf_field_names:
                    ocf_3y = self._get_value(self.cash_flow_a, field_name, 3)
                    if ocf_3y is not None:
                        break
                capex_3y = self._get_value(self.cash_flow_a, "Capital Expenditure", 3)
                fcf_3y = ocf_3y + capex_3y if ocf_3y and capex_3y else None

            growth["fcf"]["1y"] = self._calculate_growth_rate(fcf_current, fcf_1y)
            growth["fcf"]["3y_cagr"] = self._calculate_cagr(fcf_current, fcf_3y, 3)
            growth["fcf"]["current"] = fcf_current

        return growth

    def _calculate_cagr(
        self, current: Optional[float], past: Optional[float], years: int
    ) -> Optional[float]:
        """Calculate Compound Annual Growth Rate"""
        if current is None or past is None or past == 0 or years == 0:
            return None
        if past < 0:
            return None
        return calculate_cagr(current, past, years)

    # ==================== FCF Analysis ====================

    def calculate_fcf_metrics(self) -> Dict[str, Any]:
        """
        Calculate Free Cash Flow metrics

        Returns:
            Dictionary with FCF yield, FCF/share, FCF margin
        """
        fcf_metrics = {}

        # Get FCF from cash flow statement
        if self.cash_flow_a is not None and not self.cash_flow_a.empty:
            # Try to get FCF directly first (some providers include it)
            fcf = self._get_value(self.cash_flow_a, "Free Cash Flow", 0)

            # If not available, calculate from OCF - CapEx
            if fcf is None:
                # Try multiple field name variants for Operating Cash Flow
                ocf_field_names = [
                    "Operating Cash Flow",
                    "Cash Flowsfromusedin Operating Activities Direct",
                    "Total Cash From Operating Activities",
                    "Net Cash Provided By Operating Activities",
                ]
                ocf = None
                for field_name in ocf_field_names:
                    ocf = self._get_value(self.cash_flow_a, field_name, 0)
                    if ocf is not None:
                        break

                capex = self._get_value(self.cash_flow_a, "Capital Expenditure", 0)

                if ocf and capex:
                    fcf = ocf + capex  # CapEx is negative

            if fcf:
                fcf_metrics["fcf"] = fcf

                # FCF Yield = FCF / Market Cap
                market_cap = self.info.get("market_cap")
                if market_cap:
                    fcf_metrics["fcf_yield"] = (fcf / market_cap) * 100

                # FCF per Share
                shares_outstanding = self.info.get("shares_outstanding") or self.info.get(
                    "sharesOutstanding"
                )
                if shares_outstanding:
                    fcf_metrics["fcf_per_share"] = fcf / shares_outstanding

                # FCF Margin = FCF / Revenue
                revenue = self._get_value(self.income_stmt_a, "Total Revenue", 0)
                if revenue:
                    fcf_metrics["fcf_margin"] = (fcf / revenue) * 100

        return fcf_metrics

    # ==================== Margin Analysis ====================

    def calculate_margins(self) -> Dict[str, Any]:
        """
        Calculate profitability margins with trends

        Returns:
            Dictionary with margin metrics and trends
        """
        margins = {"current": {}, "trend": {}}

        if self.income_stmt_a is not None and not self.income_stmt_a.empty:
            # Get current period values
            revenue = self._get_value(self.income_stmt_a, "Total Revenue", 0)
            gross_profit = self._get_value(self.income_stmt_a, "Gross Profit", 0)
            operating_income = self._get_value(self.income_stmt_a, "Operating Income", 0)
            ebitda = self._get_value(self.income_stmt_a, "EBITDA", 0)
            net_income = self._get_value(self.income_stmt_a, "Net Income", 0)

            # Current margins
            if revenue:
                if gross_profit:
                    margins["current"]["gross_margin"] = (gross_profit / revenue) * 100
                if operating_income:
                    margins["current"]["operating_margin"] = (operating_income / revenue) * 100
                if ebitda:
                    margins["current"]["ebitda_margin"] = (ebitda / revenue) * 100
                if net_income:
                    margins["current"]["net_margin"] = (net_income / revenue) * 100

            # Calculate trend (3-year average and direction)
            for i, period in enumerate(["current", "1y_ago", "2y_ago"]):
                revenue_p = self._get_value(self.income_stmt_a, "Total Revenue", i)
                net_income_p = self._get_value(self.income_stmt_a, "Net Income", i)

                if revenue_p and net_income_p:
                    margin = (net_income_p / revenue_p) * 100
                    margins["trend"][period] = margin

        # Fallback to ticker.info
        if not margins["current"]:
            if self.info.get("profit_margin"):
                margins["current"]["net_margin"] = self.info["profit_margin"] * 100
            if self.info.get("operating_margin"):
                margins["current"]["operating_margin"] = self.info["operating_margin"] * 100

        return margins

    # ==================== Efficiency Ratios ====================

    def calculate_efficiency_ratios(self) -> Dict[str, Any]:
        """
        Calculate asset utilization and efficiency metrics

        Returns:
            Dictionary with efficiency ratios
        """
        efficiency = {}

        if self.balance_sheet_a is not None and self.income_stmt_a is not None:
            # Asset Turnover = Revenue / Total Assets
            revenue = self._get_value(self.income_stmt_a, "Total Revenue", 0)
            total_assets = self._get_value(self.balance_sheet_a, "Total Assets", 0)
            efficiency["asset_turnover"] = self._safe_divide(revenue, total_assets)

            # Inventory Turnover = COGS / Average Inventory
            cogs = self._get_value(self.income_stmt_a, "Cost Of Revenue", 0)
            inventory_current = self._get_value(self.balance_sheet_a, "Inventory", 0)
            inventory_previous = self._get_value(self.balance_sheet_a, "Inventory", 1)

            if inventory_current and inventory_previous:
                avg_inventory = (inventory_current + inventory_previous) / 2
                efficiency["inventory_turnover"] = self._safe_divide(cogs, avg_inventory)

                # Days Inventory Outstanding
                if efficiency["inventory_turnover"]:
                    efficiency["days_inventory_outstanding"] = (
                        365 / efficiency["inventory_turnover"]
                    )

            # Receivables Turnover
            accounts_receivable = self._get_value(self.balance_sheet_a, "Accounts Receivable", 0)
            accounts_receivable_prev = self._get_value(
                self.balance_sheet_a, "Accounts Receivable", 1
            )

            if accounts_receivable and accounts_receivable_prev:
                avg_receivables = (accounts_receivable + accounts_receivable_prev) / 2
                efficiency["receivables_turnover"] = self._safe_divide(revenue, avg_receivables)

                # Days Sales Outstanding
                if efficiency["receivables_turnover"]:
                    efficiency["days_sales_outstanding"] = 365 / efficiency["receivables_turnover"]

            # Payables Turnover
            accounts_payable = self._get_value(self.balance_sheet_a, "Accounts Payable", 0)
            accounts_payable_prev = self._get_value(self.balance_sheet_a, "Accounts Payable", 1)

            if accounts_payable and accounts_payable_prev and cogs:
                avg_payables = (accounts_payable + accounts_payable_prev) / 2
                efficiency["payables_turnover"] = self._safe_divide(cogs, avg_payables)

                # Days Payable Outstanding
                if efficiency["payables_turnover"]:
                    efficiency["days_payable_outstanding"] = 365 / efficiency["payables_turnover"]

            # Cash Conversion Cycle
            dio = efficiency.get("days_inventory_outstanding")
            dso = efficiency.get("days_sales_outstanding")
            dpo = efficiency.get("days_payable_outstanding")

            if dio and dso and dpo:
                efficiency["cash_conversion_cycle"] = dio + dso - dpo

        return efficiency

    # ==================== DuPont Analysis ====================

    def calculate_dupont_analysis(self) -> Dict[str, Any]:
        """
        Decompose ROE into profit margin, asset turnover, and financial leverage

        ROE = Net Margin × Asset Turnover × Equity Multiplier

        Returns:
            Dictionary with DuPont components
        """
        dupont = {}

        if self.balance_sheet_a is not None and self.income_stmt_a is not None:
            # Get components
            net_income = self._get_value(self.income_stmt_a, "Net Income", 0)
            revenue = self._get_value(self.income_stmt_a, "Total Revenue", 0)
            total_assets = self._get_value(self.balance_sheet_a, "Total Assets", 0)
            total_equity = self._get_value(self.balance_sheet_a, "Stockholders Equity", 0)

            # Calculate components
            net_margin = self._safe_divide(net_income, revenue)
            asset_turnover = self._safe_divide(revenue, total_assets)
            equity_multiplier = self._safe_divide(total_assets, total_equity)

            if net_margin is not None:
                dupont["net_margin"] = net_margin * 100
            if asset_turnover is not None:
                dupont["asset_turnover"] = asset_turnover
            if equity_multiplier is not None:
                dupont["equity_multiplier"] = equity_multiplier

            # Calculate ROE
            if all(x is not None for x in [net_margin, asset_turnover, equity_multiplier]):
                # Type assertions after all() check
                assert (
                    net_margin is not None
                    and asset_turnover is not None
                    and equity_multiplier is not None
                )
                dupont["roe_calculated"] = (net_margin * asset_turnover * equity_multiplier) * 100

            # Compare to reported ROE
            roe_reported = self.info.get("roe")
            if roe_reported:
                dupont["roe_reported"] = roe_reported * 100

        return dupont

    # ==================== Quality Scores ====================

    def calculate_altman_z_score(self) -> Optional[float]:
        """
        Calculate Altman Z-Score for bankruptcy prediction

        Z = 1.2*X1 + 1.4*X2 + 3.3*X3 + 0.6*X4 + 1.0*X5

        Where:
        X1 = Working Capital / Total Assets
        X2 = Retained Earnings / Total Assets
        X3 = EBIT / Total Assets
        X4 = Market Cap / Total Liabilities
        X5 = Sales / Total Assets

        Interpretation:
        > 2.99: Safe zone
        1.81 - 2.99: Grey zone
        < 1.81: Distress zone

        Returns:
            Z-Score value or None if insufficient data
        """
        if self.balance_sheet_a is None or self.income_stmt_a is None:
            logger.warning(
                f"Cannot calculate Altman Z-Score: Missing financial statements "
                f"(balance_sheet={self.balance_sheet_a is not None}, "
                f"income_stmt={self.income_stmt_a is not None})"
            )
            return None

        # Get balance sheet items
        current_assets = self._get_value(self.balance_sheet_a, "Current Assets", 0)
        current_liabilities = self._get_value(self.balance_sheet_a, "Current Liabilities", 0)
        total_assets = self._get_value(self.balance_sheet_a, "Total Assets", 0)
        retained_earnings = self._get_value(self.balance_sheet_a, "Retained Earnings", 0)
        total_liabilities = self._get_value(
            self.balance_sheet_a, "Total Liabilities Net Minority Interest", 0
        )

        # Get income statement items
        ebit = self._get_value(self.income_stmt_a, "EBIT", 0)
        revenue = self._get_value(self.income_stmt_a, "Total Revenue", 0)

        # Get market cap
        market_cap = self.info.get("market_cap")

        # Calculate components
        if not all(
            [
                current_assets,
                current_liabilities,
                total_assets,
                retained_earnings,
                total_liabilities,
                ebit,
                revenue,
                market_cap,
            ]
        ):
            missing = []
            if not current_assets:
                missing.append("Current Assets")
            if not current_liabilities:
                missing.append("Current Liabilities")
            if not total_assets:
                missing.append("Total Assets")
            if not retained_earnings:
                missing.append("Retained Earnings")
            if not total_liabilities:
                missing.append("Total Liabilities")
            if not ebit:
                missing.append("EBIT")
            if not revenue:
                missing.append("Revenue")
            if not market_cap:
                missing.append("Market Cap")

            logger.warning(f"Altman Z-Score incomplete: Missing {', '.join(missing)}")
            return None

        # Type assertions for narrowing Optional[float] -> float
        assert current_assets is not None and current_liabilities is not None
        assert total_assets is not None and retained_earnings is not None
        assert total_liabilities is not None and ebit is not None
        assert revenue is not None and market_cap is not None

        working_capital = current_assets - current_liabilities

        x1 = working_capital / total_assets
        x2 = retained_earnings / total_assets
        x3 = ebit / total_assets
        x4 = market_cap / total_assets
        x5 = revenue / total_assets

        z_score = 1.2 * x1 + 1.4 * x2 + 3.3 * x3 + 0.6 * x4 + 1.0 * x5

        return z_score

    def calculate_piotroski_f_score(self) -> Optional[int]:
        """
        Calculate Piotroski F-Score (0-9) for fundamental strength

        9 criteria across profitability, leverage, and operating efficiency:

        Profitability (4 points):
        1. Positive net income
        2. Positive operating cash flow
        3. ROA increasing
        4. Quality of earnings (OCF > Net Income)

        Leverage/Liquidity (3 points):
        5. Decreasing long-term debt
        6. Increasing current ratio
        7. No new shares issued

        Operating Efficiency (2 points):
        8. Increasing gross margin
        9. Increasing asset turnover

        Interpretation:
        8-9: Strong
        5-7: Average
        0-4: Weak

        Returns:
            F-Score (0-9) or None if insufficient data
        """
        if self.balance_sheet_a is None or self.income_stmt_a is None or self.cash_flow_a is None:
            missing = []
            if self.balance_sheet_a is None:
                missing.append("balance sheet")
            if self.income_stmt_a is None:
                missing.append("income statement")
            if self.cash_flow_a is None:
                missing.append("cash flow")

            logger.warning(f"Cannot calculate Piotroski F-Score: Missing {', '.join(missing)}")
            return None

        score = 0

        # 1. Positive Net Income
        net_income = self._get_value(self.income_stmt_a, "Net Income", 0)
        if net_income and net_income > 0:
            score += 1

        # 2. Positive Operating Cash Flow
        ocf = self._get_value(self.cash_flow_a, "Operating Cash Flow", 0)
        if ocf and ocf > 0:
            score += 1

        # 3. ROA Increasing
        net_income_prev = self._get_value(self.income_stmt_a, "Net Income", 1)
        total_assets = self._get_value(self.balance_sheet_a, "Total Assets", 0)
        total_assets_prev = self._get_value(self.balance_sheet_a, "Total Assets", 1)

        if (
            net_income is not None
            and net_income_prev is not None
            and total_assets is not None
            and total_assets_prev is not None
        ):
            roa_current = net_income / total_assets
            roa_prev = net_income_prev / total_assets_prev
            if roa_current > roa_prev:
                score += 1

        # 4. Quality of Earnings (OCF > Net Income)
        if ocf and net_income and ocf > net_income:
            score += 1

        # 5. Decreasing Long-Term Debt
        lt_debt = self._get_value(self.balance_sheet_a, "Long Term Debt", 0)
        lt_debt_prev = self._get_value(self.balance_sheet_a, "Long Term Debt", 1)
        if lt_debt is not None and lt_debt_prev is not None:
            if lt_debt < lt_debt_prev:
                score += 1

        # 6. Increasing Current Ratio
        current_assets = self._get_value(self.balance_sheet_a, "Current Assets", 0)
        current_liabilities = self._get_value(self.balance_sheet_a, "Current Liabilities", 0)
        current_assets_prev = self._get_value(self.balance_sheet_a, "Current Assets", 1)
        current_liabilities_prev = self._get_value(self.balance_sheet_a, "Current Liabilities", 1)

        if (
            current_assets is not None
            and current_liabilities is not None
            and current_assets_prev is not None
            and current_liabilities_prev is not None
        ):
            current_ratio = current_assets / current_liabilities
            current_ratio_prev = current_assets_prev / current_liabilities_prev
            if current_ratio > current_ratio_prev:
                score += 1

        # 7. No New Shares Issued
        # Requires historical shares data which yfinance doesn't always provide — skip
        _ = self.info.get("shares_outstanding") or self.info.get("sharesOutstanding")

        # 8. Increasing Gross Margin
        revenue = self._get_value(self.income_stmt_a, "Total Revenue", 0)
        gross_profit = self._get_value(self.income_stmt_a, "Gross Profit", 0)
        revenue_prev = self._get_value(self.income_stmt_a, "Total Revenue", 1)
        gross_profit_prev = self._get_value(self.income_stmt_a, "Gross Profit", 1)

        if (
            revenue is not None
            and gross_profit is not None
            and revenue_prev is not None
            and gross_profit_prev is not None
        ):
            gross_margin = gross_profit / revenue
            gross_margin_prev = gross_profit_prev / revenue_prev
            if gross_margin > gross_margin_prev:
                score += 1

        # 9. Increasing Asset Turnover
        if revenue is not None and total_assets is not None:
            # revenue_prev and total_assets_prev already exist from earlier checks
            revenue_prev_at = self._get_value(
                self.income_stmt_a, "Total Revenue", 1
            )  # Get again to be safe
            total_assets_prev_at = self._get_value(self.balance_sheet_a, "Total Assets", 1)
            if revenue_prev_at is not None and total_assets_prev_at is not None:
                asset_turnover = revenue / total_assets
                asset_turnover_prev = revenue_prev_at / total_assets_prev_at
                if asset_turnover > asset_turnover_prev:
                    score += 1

        return score

    # ==================== Forensic / Earnings Quality ====================

    def calculate_beneish_m_score(self) -> Optional[Dict[str, Any]]:
        """
        Calculate Beneish M-Score for earnings manipulation detection

        M-Score = -4.84 + 0.920*DSRI + 0.528*GMI + 0.404*AQI + 0.892*SGI
                  + 0.115*DEPI - 0.172*SGAI + 4.679*TATA - 0.327*LVGI

        Variables:
        - DSRI: Days Sales in Receivables Index
        - GMI: Gross Margin Index
        - AQI: Asset Quality Index
        - SGI: Sales Growth Index
        - DEPI: Depreciation Index
        - SGAI: SG&A Index (Selling, General & Administrative)
        - TATA: Total Accruals to Total Assets
        - LVGI: Leverage Index

        Interpretation:
        > -1.78: Likely manipulator (high probability of earnings manipulation)
        <= -1.78: Unlikely manipulator

        Returns:
            Dictionary with M-Score value, components, and interpretation, or None
        """
        if self.balance_sheet_a is None or self.income_stmt_a is None or self.cash_flow_a is None:
            logger.warning("Cannot calculate Beneish M-Score: Missing financial statements")
            return None

        # Current period (index 0) and prior period (index 1)
        revenue_t = self._get_value(self.income_stmt_a, "Total Revenue", 0)
        revenue_t1 = self._get_value(self.income_stmt_a, "Total Revenue", 1)
        cogs_t = self._get_value(self.income_stmt_a, "Cost Of Revenue", 0)
        cogs_t1 = self._get_value(self.income_stmt_a, "Cost Of Revenue", 1)
        net_income_t = self._get_value(self.income_stmt_a, "Net Income", 0)
        sga_t = self._get_value(self.income_stmt_a, "Selling General And Administration", 0)
        sga_t1 = self._get_value(self.income_stmt_a, "Selling General And Administration", 1)
        depreciation_t = self._get_value(self.income_stmt_a, "Reconciled Depreciation", 0)
        depreciation_t1 = self._get_value(self.income_stmt_a, "Reconciled Depreciation", 1)

        receivables_t = self._get_value(self.balance_sheet_a, "Accounts Receivable", 0)
        receivables_t1 = self._get_value(self.balance_sheet_a, "Accounts Receivable", 1)
        total_assets_t = self._get_value(self.balance_sheet_a, "Total Assets", 0)
        total_assets_t1 = self._get_value(self.balance_sheet_a, "Total Assets", 1)
        current_assets_t = self._get_value(self.balance_sheet_a, "Current Assets", 0)
        current_assets_t1 = self._get_value(self.balance_sheet_a, "Current Assets", 1)
        ppe_t = self._get_value(self.balance_sheet_a, "Net PPE", 0)
        ppe_t1 = self._get_value(self.balance_sheet_a, "Net PPE", 1)
        current_liabilities_t = self._get_value(self.balance_sheet_a, "Current Liabilities", 0)
        current_liabilities_t1 = self._get_value(self.balance_sheet_a, "Current Liabilities", 1)
        long_term_debt_t = self._get_value(self.balance_sheet_a, "Long Term Debt", 0)
        long_term_debt_t1 = self._get_value(self.balance_sheet_a, "Long Term Debt", 1)

        ocf_t = self._get_value(self.cash_flow_a, "Operating Cash Flow", 0)

        # Validate minimum required data
        if not all([revenue_t, revenue_t1, total_assets_t, total_assets_t1]):
            logger.warning("Beneish M-Score: Insufficient data (missing revenue or total assets)")
            return None

        assert revenue_t is not None and revenue_t1 is not None
        assert total_assets_t is not None and total_assets_t1 is not None

        if revenue_t1 == 0 or total_assets_t1 == 0:
            return None

        components = {}
        available_count = 0

        # DSRI: Days Sales in Receivables Index
        # (Receivables_t / Revenue_t) / (Receivables_t-1 / Revenue_t-1)
        dsri = None
        if receivables_t and receivables_t1 and revenue_t1 != 0:
            ratio_t = receivables_t / revenue_t
            ratio_t1 = receivables_t1 / revenue_t1
            if ratio_t1 != 0:
                dsri = ratio_t / ratio_t1
                components["dsri"] = dsri
                available_count += 1

        # GMI: Gross Margin Index
        # ((Revenue_t-1 - COGS_t-1) / Revenue_t-1) / ((Revenue_t - COGS_t) / Revenue_t)
        gmi = None
        if cogs_t and cogs_t1:
            gm_t = (revenue_t - cogs_t) / revenue_t
            gm_t1 = (revenue_t1 - cogs_t1) / revenue_t1
            if gm_t != 0:
                gmi = gm_t1 / gm_t
                components["gmi"] = gmi
                available_count += 1

        # AQI: Asset Quality Index
        # (1 - (CA_t + PPE_t) / TA_t) / (1 - (CA_t-1 + PPE_t-1) / TA_t-1)
        aqi = None
        if current_assets_t and ppe_t and current_assets_t1 and ppe_t1:
            aq_t = 1 - (current_assets_t + ppe_t) / total_assets_t
            aq_t1 = 1 - (current_assets_t1 + ppe_t1) / total_assets_t1
            if aq_t1 != 0:
                aqi = aq_t / aq_t1
                components["aqi"] = aqi
                available_count += 1

        # SGI: Sales Growth Index
        # Revenue_t / Revenue_t-1
        sgi = revenue_t / revenue_t1
        components["sgi"] = sgi
        available_count += 1

        # DEPI: Depreciation Index
        # (Dep_t-1 / (Dep_t-1 + PPE_t-1)) / (Dep_t / (Dep_t + PPE_t))
        depi = None
        if depreciation_t and depreciation_t1 and ppe_t and ppe_t1:
            dep_rate_t = depreciation_t / (depreciation_t + ppe_t)
            dep_rate_t1 = depreciation_t1 / (depreciation_t1 + ppe_t1)
            if dep_rate_t != 0:
                depi = dep_rate_t1 / dep_rate_t
                components["depi"] = depi
                available_count += 1

        # SGAI: SG&A Index
        # (SGA_t / Revenue_t) / (SGA_t-1 / Revenue_t-1)
        sgai = None
        if sga_t and sga_t1:
            sga_ratio_t = sga_t / revenue_t
            sga_ratio_t1 = sga_t1 / revenue_t1
            if sga_ratio_t1 != 0:
                sgai = sga_ratio_t / sga_ratio_t1
                components["sgai"] = sgai
                available_count += 1

        # TATA: Total Accruals to Total Assets
        # (Net Income - OCF) / Total Assets
        tata = None
        if net_income_t is not None and ocf_t is not None:
            tata = (net_income_t - ocf_t) / total_assets_t
            components["tata"] = tata
            available_count += 1

        # LVGI: Leverage Index
        # ((CL_t + LTD_t) / TA_t) / ((CL_t-1 + LTD_t-1) / TA_t-1)
        lvgi = None
        if (
            current_liabilities_t is not None
            and long_term_debt_t is not None
            and current_liabilities_t1 is not None
            and long_term_debt_t1 is not None
        ):
            lev_t = (current_liabilities_t + long_term_debt_t) / total_assets_t
            lev_t1 = (current_liabilities_t1 + long_term_debt_t1) / total_assets_t1
            if lev_t1 != 0:
                lvgi = lev_t / lev_t1
                components["lvgi"] = lvgi
                available_count += 1

        # Need at least 5 of 8 components for a meaningful score
        if available_count < 5:
            logger.warning(f"Beneish M-Score: Only {available_count}/8 components available")
            return None

        # Calculate M-Score using available components (use 1.0 for missing indices)
        m_score = (
            -4.84
            + 0.920 * (dsri if dsri is not None else 1.0)
            + 0.528 * (gmi if gmi is not None else 1.0)
            + 0.404 * (aqi if aqi is not None else 1.0)
            + 0.892 * sgi
            + 0.115 * (depi if depi is not None else 1.0)
            - 0.172 * (sgai if sgai is not None else 1.0)
            + 4.679 * (tata if tata is not None else 0.0)
            - 0.327 * (lvgi if lvgi is not None else 1.0)
        )

        # Interpretation
        if m_score > -1.78:
            interpretation = "likely_manipulator"
            risk_level = "high"
        elif m_score > -2.22:
            interpretation = "grey_zone"
            risk_level = "moderate"
        else:
            interpretation = "unlikely_manipulator"
            risk_level = "low"

        return {
            "m_score": m_score,
            "interpretation": interpretation,
            "risk_level": risk_level,
            "threshold": -1.78,
            "components": components,
            "components_available": available_count,
        }

    def calculate_accruals_quality(self) -> Optional[Dict[str, Any]]:
        """
        Calculate Sloan Accrual Ratio for earnings quality assessment

        Accrual Ratio = (Net Income - Operating Cash Flow) / Total Assets

        High accruals (>10%) indicate lower earnings quality and predict
        future underperformance. One of the most robust anomalies in
        academic finance (Sloan, 1996).

        Interpretation:
        < 5%: High quality (cash-backed earnings)
        5-10%: Moderate quality
        > 10%: Low quality (accrual-heavy earnings)
        Negative: Very high quality (cash earnings exceed reported)

        Returns:
            Dictionary with accrual ratio and interpretation, or None
        """
        if self.income_stmt_a is None or self.cash_flow_a is None or self.balance_sheet_a is None:
            return None

        net_income = self._get_value(self.income_stmt_a, "Net Income", 0)
        ocf = self._get_value(self.cash_flow_a, "Operating Cash Flow", 0)
        total_assets = self._get_value(self.balance_sheet_a, "Total Assets", 0)

        # Try average total assets for more accuracy
        total_assets_prev = self._get_value(self.balance_sheet_a, "Total Assets", 1)
        if total_assets and total_assets_prev:
            avg_total_assets = (total_assets + total_assets_prev) / 2
        else:
            avg_total_assets = total_assets

        if net_income is None or ocf is None or not avg_total_assets:
            return None

        # Sloan accrual ratio
        accruals = net_income - ocf
        accrual_ratio = (accruals / avg_total_assets) * 100  # As percentage

        # Interpretation
        abs_ratio = abs(accrual_ratio)
        if accrual_ratio < 0:
            quality = "very_high"
            interpretation = "Cash earnings exceed reported income"
        elif abs_ratio <= 5:
            quality = "high"
            interpretation = "Earnings well-supported by cash flows"
        elif abs_ratio <= 10:
            quality = "moderate"
            interpretation = "Some earnings not backed by cash"
        else:
            quality = "low"
            interpretation = "High accruals - earnings quality concern"

        return {
            "accrual_ratio_pct": accrual_ratio,
            "net_income": net_income,
            "operating_cash_flow": ocf,
            "total_accruals": accruals,
            "quality": quality,
            "interpretation": interpretation,
        }

    def calculate_cash_conversion(self) -> Optional[Dict[str, Any]]:
        """
        Calculate Cash Conversion Score (CFO / EBITDA)

        Measures how much of reported EBITDA converts to actual operating cash.
        Persistent low conversion is a red flag for earnings quality.

        Interpretation:
        > 100%: Excellent (more cash than EBITDA - working capital benefit)
        80-100%: Good (normal conversion)
        60-80%: Fair (some cash leakage)
        < 60%: Poor (significant gap between earnings and cash)

        Returns:
            Dictionary with conversion metrics, or None
        """
        if self.cash_flow_a is None or self.income_stmt_a is None:
            return None

        ocf = self._get_value(self.cash_flow_a, "Operating Cash Flow", 0)
        ebitda = self._get_value(self.income_stmt_a, "EBITDA", 0)

        if ocf is None or ebitda is None or ebitda == 0:
            return None

        conversion_ratio = (ocf / ebitda) * 100

        # Historical trend (3 years)
        trend = []
        for i in range(3):
            ocf_i = self._get_value(self.cash_flow_a, "Operating Cash Flow", i)
            ebitda_i = self._get_value(self.income_stmt_a, "EBITDA", i)
            if ocf_i is not None and ebitda_i is not None and ebitda_i != 0:
                trend.append((ocf_i / ebitda_i) * 100)

        # Interpretation
        if conversion_ratio > 100:
            quality = "excellent"
        elif conversion_ratio >= 80:
            quality = "good"
        elif conversion_ratio >= 60:
            quality = "fair"
        else:
            quality = "poor"

        # Check for persistent poor conversion
        persistent_poor = len(trend) >= 2 and all(r < 60 for r in trend)

        return {
            "conversion_ratio_pct": conversion_ratio,
            "operating_cash_flow": ocf,
            "ebitda": ebitda,
            "quality": quality,
            "trend": trend,
            "persistent_poor_conversion": persistent_poor,
        }

    # ==================== Aggregation Methods ====================

    def calculate_all(self) -> Dict[str, Any]:
        """
        Calculate all fundamental metrics

        Returns:
            Dictionary with all analysis results
        """
        logger.info("Calculating fundamental metrics...")

        results = {
            "growth_rates": self.calculate_growth_rates(),
            "fcf_metrics": self.calculate_fcf_metrics(),
            "margins": self.calculate_margins(),
            "efficiency": self.calculate_efficiency_ratios(),
            "dupont": self.calculate_dupont_analysis(),
            "quality_scores": {
                "altman_z": self.calculate_altman_z_score(),
                "piotroski_f": self.calculate_piotroski_f_score(),
                "beneish_m": self.calculate_beneish_m_score(),
                "accruals_quality": self.calculate_accruals_quality(),
                "cash_conversion": self.calculate_cash_conversion(),
            },
        }

        logger.info("Fundamental analysis complete")
        return results

    def get_summary(self) -> Dict[str, Any]:
        """
        Get comprehensive fundamental analysis summary

        Returns:
            Dictionary suitable for JSON export
        """
        return {
            "ticker": self.info.get("symbol"),
            "company_name": self.info.get("name"),
            "sector": self.info.get("sector"),
            "industry": self.info.get("industry"),
            "analysis": self.calculate_all(),
        }

    def format_markdown(self) -> List[str]:
        """
        Format fundamental analysis as markdown report

        Returns:
            List of markdown lines
        """
        md = []
        md.append("\n## Fundamental Analysis")
        md.append("")

        results = self.calculate_all()

        # Growth Rates
        md.append("### Growth Rates")
        md.append("")
        growth = results["growth_rates"]

        if any(growth.values()):
            md.append("| Metric | 1 Year | 3 Year CAGR | 5 Year CAGR |")
            md.append("|--------|--------|--------------|--------------|")

            revenue = growth.get("revenue", {})
            md.append(
                f"| Revenue | {self._format_pct(revenue.get('1y'))} | "
                f"{self._format_pct(revenue.get('3y_cagr'))} | "
                f"{self._format_pct(revenue.get('5y_cagr'))} |"
            )

            earnings = growth.get("earnings", {})
            md.append(
                f"| Earnings | {self._format_pct(earnings.get('1y'))} | "
                f"{self._format_pct(earnings.get('3y_cagr'))} | "
                f"{self._format_pct(earnings.get('5y_cagr'))} |"
            )

            fcf = growth.get("fcf", {})
            md.append(
                f"| Free Cash Flow | {self._format_pct(fcf.get('1y'))} | "
                f"{self._format_pct(fcf.get('3y_cagr'))} | N/A |"
            )
            md.append("")
        else:
            md.append("*Insufficient historical data for growth analysis*")
            md.append("")

        # Free Cash Flow Metrics
        md.append("### Free Cash Flow Analysis")
        md.append("")
        fcf_metrics = results["fcf_metrics"]

        if fcf_metrics:
            md.append("| Metric | Value |")
            md.append("|--------|-------|")

            if fcf_metrics.get("fcf"):
                md.append(f"| Free Cash Flow | ${fcf_metrics['fcf']:,.0f} |")
            if fcf_metrics.get("fcf_yield"):
                md.append(f"| FCF Yield | {fcf_metrics['fcf_yield']:.2f}% |")
            if fcf_metrics.get("fcf_per_share"):
                md.append(f"| FCF per Share | ${fcf_metrics['fcf_per_share']:.2f} |")
            if fcf_metrics.get("fcf_margin"):
                md.append(f"| FCF Margin | {fcf_metrics['fcf_margin']:.2f}% |")
            md.append("")
        else:
            md.append("*FCF data unavailable*")
            md.append("")

        # Profitability Margins
        md.append("### Profitability Margins")
        md.append("")
        margins = results["margins"]

        if margins.get("current"):
            md.append("| Margin Type | Current |")
            md.append("|-------------|---------|")

            current = margins["current"]
            if current.get("gross_margin"):
                md.append(f"| Gross Margin | {current['gross_margin']:.2f}% |")
            if current.get("ebitda_margin"):
                md.append(f"| EBITDA Margin | {current['ebitda_margin']:.2f}% |")
            if current.get("operating_margin"):
                md.append(f"| Operating Margin | {current['operating_margin']:.2f}% |")
            if current.get("net_margin"):
                md.append(f"| Net Margin | {current['net_margin']:.2f}% |")
            md.append("")

            # Margin trend
            trend = margins.get("trend", {})
            if len(trend) >= 2:
                current_margin = trend.get("current")
                prev_margin = trend.get("1y_ago")
                if current_margin and prev_margin:
                    direction = "↑ Improving" if current_margin > prev_margin else "↓ Declining"
                    md.append(f"**Trend:** Net margin {direction}")
                    md.append("")
        else:
            md.append("*Margin data unavailable*")
            md.append("")

        # Efficiency Ratios
        md.append("### Efficiency Ratios")
        md.append("")
        efficiency = results["efficiency"]

        if efficiency:
            md.append("| Ratio | Value |")
            md.append("|-------|-------|")

            if efficiency.get("asset_turnover"):
                md.append(f"| Asset Turnover | {efficiency['asset_turnover']:.2f}x |")
            if efficiency.get("inventory_turnover"):
                md.append(f"| Inventory Turnover | {efficiency['inventory_turnover']:.2f}x |")
            if efficiency.get("days_inventory_outstanding"):
                md.append(
                    f"| Days Inventory Outstanding | {efficiency['days_inventory_outstanding']:.0f} days |"
                )
            if efficiency.get("receivables_turnover"):
                md.append(f"| Receivables Turnover | {efficiency['receivables_turnover']:.2f}x |")
            if efficiency.get("days_sales_outstanding"):
                md.append(
                    f"| Days Sales Outstanding | {efficiency['days_sales_outstanding']:.0f} days |"
                )
            if efficiency.get("cash_conversion_cycle"):
                md.append(
                    f"| Cash Conversion Cycle | {efficiency['cash_conversion_cycle']:.0f} days |"
                )
            md.append("")
        else:
            md.append("*Efficiency data unavailable*")
            md.append("")

        # DuPont Analysis
        md.append("### DuPont ROE Analysis")
        md.append("")
        dupont = results["dupont"]

        if dupont:
            md.append("| Component | Value |")
            md.append("|-----------|-------|")

            if dupont.get("net_margin"):
                md.append(f"| Net Margin | {dupont['net_margin']:.2f}% |")
            if dupont.get("asset_turnover"):
                md.append(f"| Asset Turnover | {dupont['asset_turnover']:.2f}x |")
            if dupont.get("equity_multiplier"):
                md.append(f"| Equity Multiplier | {dupont['equity_multiplier']:.2f}x |")
            if dupont.get("roe_calculated"):
                md.append(f"| **ROE (Calculated)** | **{dupont['roe_calculated']:.2f}%** |")
            if dupont.get("roe_reported"):
                md.append(f"| ROE (Reported) | {dupont['roe_reported']:.2f}% |")
            md.append("")
            md.append("*ROE = Net Margin × Asset Turnover × Equity Multiplier*")
            md.append("")
        else:
            md.append("*DuPont analysis unavailable*")
            md.append("")

        # Quality Scores
        md.append("### Quality & Integrity Scores")
        md.append("")
        md.append(
            "> *These scores detect financial health problems and earnings manipulation "
            "that standard metrics might miss.*"
        )
        md.append("")
        quality = results["quality_scores"]

        # Altman Z-Score
        z_score = quality.get("altman_z")
        if z_score:
            if z_score > self.config.z_score_safe:
                z_interp = "Safe — low bankruptcy risk"
            elif z_score > self.config.z_score_distress:
                z_interp = "Grey zone — some financial stress"
            else:
                z_interp = "Distress — elevated bankruptcy risk"
            md.append(f"**Altman Z-Score: {z_score:.2f}** — {z_interp}")
            md.append("")
            md.append("> *Predicts bankruptcy risk. Above 2.99 = safe, below 1.81 = danger.*")
            md.append("")

        # Piotroski F-Score
        f_score = quality.get("piotroski_f")
        if f_score is not None:
            if f_score >= self.config.min_f_score_strong:
                f_interp = "Strong fundamentals"
            elif f_score >= self.config.min_f_score_average:
                f_interp = "Average fundamentals"
            else:
                f_interp = "Weak fundamentals"
            md.append(f"**Piotroski F-Score: {f_score}/9** — {f_interp}")
            md.append("")
            md.append("> *Scores 9 yes/no financial health checks. 8-9 = strong, 0-4 = weak.*")
            md.append("")

        # Beneish M-Score (new)
        beneish = quality.get("beneish_m")
        if beneish and isinstance(beneish, dict):
            m_score = beneish.get("m_score")
            risk = beneish.get("risk_level", "unknown")
            if m_score is not None:
                if risk == "low":
                    m_interp = "Low manipulation risk"
                elif risk == "moderate":
                    m_interp = "Grey zone — inconclusive"
                else:
                    m_interp = "HIGH manipulation risk — earnings may be artificially inflated"
                md.append(f"**Beneish M-Score: {m_score:.2f}** — {m_interp}")
                md.append("")
                md.append(
                    "> *Detects earnings manipulation (like Enron). "
                    "Above -1.78 = likely manipulator. Lower is safer.*"
                )
                md.append("")

        # Accruals Quality (new)
        accruals = quality.get("accruals_quality")
        if accruals and isinstance(accruals, dict):
            ratio = accruals.get("accrual_ratio_pct")
            if ratio is not None:
                md.append(
                    f"**Earnings Quality (Accruals): {ratio:.1f}%** — {accruals.get('interpretation', '')}"
                )
                md.append("")
                md.append(
                    "> *Measures how much of reported earnings is real cash vs. accounting entries. "
                    "Negative = great (cash exceeds reported). High positive = concern.*"
                )
                md.append("")

        # Cash Conversion (new)
        cash_conv = quality.get("cash_conversion")
        if cash_conv and isinstance(cash_conv, dict):
            conv_ratio = cash_conv.get("conversion_ratio_pct")
            conv_qual = cash_conv.get("quality", "unknown")
            if conv_ratio is not None:
                md.append(f"**Cash Conversion: {conv_ratio:.0f}%** — {conv_qual.title()}")
                md.append("")
                md.append(
                    "> *What percentage of reported EBITDA actually becomes cash? "
                    "80%+ is healthy. Below 60% persistently is a red flag.*"
                )
                if cash_conv.get("persistent_poor_conversion"):
                    md.append("")
                    md.append("**Warning:** Persistently poor cash conversion over multiple years")
                md.append("")

        return md

    def _format_pct(self, value: Optional[float]) -> str:
        """Format percentage value for display"""
        if value is None:
            return "N/A"
        return f"{value:+.2f}%"


# ==================== Standalone Functions ====================


def calculate_pead_signal(
    earnings_history: List[Dict[str, Any]],
    price_data: Optional[pd.DataFrame] = None,
) -> Optional[Dict[str, Any]]:
    """
    Calculate Post-Earnings Announcement Drift (PEAD) signal.

    PEAD is one of the most well-documented market anomalies: stocks that
    beat earnings estimates tend to drift UP for 60-90 days after the
    announcement, and stocks that miss tend to drift DOWN.

    Computes Standardized Unexpected Earnings (SUE):
        SUE = (Actual EPS - Estimate EPS) / Std(Surprise)

    A positive SUE > 1.0 is a buy signal; negative SUE < -1.0 is bearish.

    Args:
        earnings_history: List of dicts with 'quarter', 'epsActual',
                         'epsEstimate', 'epsDifference', 'surprisePercent'
        price_data: Optional DataFrame with 'Close' prices to check
                   post-announcement price drift confirmation

    Returns:
        Dictionary with PEAD signal analysis, or None if insufficient data
    """
    if not earnings_history or len(earnings_history) < 2:
        return None

    # Filter to entries with valid surprise data
    valid = [
        e
        for e in earnings_history
        if e.get("epsActual") is not None
        and e.get("epsEstimate") is not None
        and e.get("epsDifference") is not None
    ]

    if len(valid) < 2:
        return None

    # Calculate surprise statistics
    surprises = [e["epsDifference"] for e in valid]

    import numpy as np

    surprise_std = float(np.std(surprises)) if len(surprises) >= 2 else None

    # Most recent earnings
    latest = valid[0]  # Assuming sorted most-recent-first
    latest_surprise = latest["epsDifference"]
    latest_surprise_pct = latest.get("surprisePercent", 0)

    # SUE (Standardized Unexpected Earnings)
    sue = None
    if surprise_std and surprise_std > 0:
        sue = latest_surprise / surprise_std

    # Streak analysis (consecutive beats/misses)
    streak = 0
    streak_direction = None
    for e in valid:
        diff = e.get("epsDifference", 0)
        if diff is None:
            break
        if diff > 0:
            if streak_direction is None or streak_direction == "beat":
                streak += 1
                streak_direction = "beat"
            else:
                break
        elif diff < 0:
            if streak_direction is None or streak_direction == "miss":
                streak += 1
                streak_direction = "miss"
            else:
                break
        else:
            break

    # Drift confirmation from price data (if available)
    drift_confirmed = None
    days_since_earnings = None
    post_earnings_return = None

    if price_data is not None and not price_data.empty and latest.get("quarter"):
        try:
            earnings_date = pd.Timestamp(latest["quarter"])
            # Find the closest trading day after earnings
            prices_after = price_data[price_data.index >= earnings_date]
            if len(prices_after) >= 2:
                days_since_earnings = len(prices_after)
                price_at_earnings = float(prices_after["Close"].iloc[0])
                price_now = float(prices_after["Close"].iloc[-1])
                if price_at_earnings > 0:
                    post_earnings_return = (price_now - price_at_earnings) / price_at_earnings

                    # Drift confirmed if price moved in same direction as surprise
                    if latest_surprise > 0 and post_earnings_return > 0:
                        drift_confirmed = True
                    elif latest_surprise < 0 and post_earnings_return < 0:
                        drift_confirmed = True
                    else:
                        drift_confirmed = False
        except Exception:
            pass

    # Signal interpretation
    if sue is not None:
        if sue > 2.0:
            signal = "strong_buy"
            interpretation = "Large positive surprise — strong drift expected"
        elif sue > 1.0:
            signal = "buy"
            interpretation = "Meaningful beat — positive drift likely"
        elif sue > 0:
            signal = "slight_positive"
            interpretation = "Small beat — mild positive drift possible"
        elif sue > -1.0:
            signal = "slight_negative"
            interpretation = "Small miss — mild negative drift possible"
        elif sue > -2.0:
            signal = "sell"
            interpretation = "Meaningful miss — negative drift likely"
        else:
            signal = "strong_sell"
            interpretation = "Large negative surprise — strong downward drift expected"
    else:
        signal = "neutral"
        interpretation = "Insufficient data for SUE calculation"

    return {
        "sue": sue,
        "signal": signal,
        "interpretation": interpretation,
        "latest_surprise_pct": latest_surprise_pct * 100
        if latest_surprise_pct and abs(latest_surprise_pct) < 10
        else latest_surprise_pct,
        "latest_eps_actual": latest.get("epsActual"),
        "latest_eps_estimate": latest.get("epsEstimate"),
        "earnings_date": latest.get("quarter"),
        "surprise_std": surprise_std,
        "streak": streak,
        "streak_direction": streak_direction,
        "drift_confirmed": drift_confirmed,
        "days_since_earnings": days_since_earnings,
        "post_earnings_return_pct": post_earnings_return * 100
        if post_earnings_return is not None
        else None,
        "sample_size": len(valid),
    }
