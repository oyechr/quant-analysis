"""
Fundamental Analysis Module
Analyzes financial statements and calculates fundamental metrics
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, List
import logging

from .serialization import format_date

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
        price_data: Optional[pd.DataFrame] = None
    ):
        """
        Initialize analyzer with financial data
        
        Args:
            ticker_info: Dictionary from yfinance ticker.info
            fundamentals: Dictionary with income_stmt, balance_sheet, cash_flow DataFrames
            price_data: Historical price data for market-based calculations
        """
        self.info = ticker_info
        self.fundamentals = fundamentals or {}
        self.price_data = price_data
        
        # Extract financial statements
        self.income_stmt_q = self.fundamentals.get('income_stmt_quarterly')
        self.income_stmt_a = self.fundamentals.get('income_stmt_annual')
        self.balance_sheet_q = self.fundamentals.get('balance_sheet_quarterly')
        self.balance_sheet_a = self.fundamentals.get('balance_sheet_annual')
        self.cash_flow_q = self.fundamentals.get('cash_flow_quarterly')
        self.cash_flow_a = self.fundamentals.get('cash_flow_annual')
    
    # ==================== Helper Methods ====================
    
    def _get_value(self, df: Optional[pd.DataFrame], row_name: str, col_index: int = 0) -> Optional[float]:
        """Safely extract value from financial statement DataFrame"""
        if df is None or df.empty:
            return None
        try:
            if row_name in df.index:
                value = df.loc[row_name].iloc[col_index]
                # Handle both scalar and Series values
                if isinstance(value, pd.Series):
                    value = value.iloc[0] if len(value) > 0 else None
                return float(value) if pd.notna(value) and value is not None else None
        except (KeyError, IndexError, ValueError, TypeError):
            pass
        return None
    
    def _calculate_growth_rate(self, current: Optional[float], previous: Optional[float]) -> Optional[float]:
        """Calculate percentage growth rate"""
        if current is None or previous is None or previous == 0:
            return None
        return ((current - previous) / abs(previous)) * 100
    
    def _safe_divide(self, numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
        """Safely divide two numbers"""
        if numerator is None or denominator is None or denominator == 0:
            return None
        return numerator / denominator
    
    # ==================== Growth Rates ====================
    
    def calculate_growth_rates(self) -> Dict[str, Any]:
        """
        Calculate revenue, earnings, and FCF growth rates for 1Y, 3Y, 5Y
        
        Returns:
            Dictionary with growth metrics
        """
        growth = {
            'revenue': {},
            'earnings': {},
            'fcf': {}
        }
        
        if self.income_stmt_a is not None and not self.income_stmt_a.empty:
            # Revenue growth
            revenue_current = self._get_value(self.income_stmt_a, 'Total Revenue', 0)
            revenue_1y = self._get_value(self.income_stmt_a, 'Total Revenue', 1)
            revenue_3y = self._get_value(self.income_stmt_a, 'Total Revenue', 3)
            revenue_5y = self._get_value(self.income_stmt_a, 'Total Revenue', 4)
            
            growth['revenue']['1y'] = self._calculate_growth_rate(revenue_current, revenue_1y)
            growth['revenue']['3y_cagr'] = self._calculate_cagr(revenue_current, revenue_3y, 3)
            growth['revenue']['5y_cagr'] = self._calculate_cagr(revenue_current, revenue_5y, 5)
            
            # Earnings growth (Net Income)
            earnings_current = self._get_value(self.income_stmt_a, 'Net Income', 0)
            earnings_1y = self._get_value(self.income_stmt_a, 'Net Income', 1)
            earnings_3y = self._get_value(self.income_stmt_a, 'Net Income', 3)
            earnings_5y = self._get_value(self.income_stmt_a, 'Net Income', 4)
            
            growth['earnings']['1y'] = self._calculate_growth_rate(earnings_current, earnings_1y)
            growth['earnings']['3y_cagr'] = self._calculate_cagr(earnings_current, earnings_3y, 3)
            growth['earnings']['5y_cagr'] = self._calculate_cagr(earnings_current, earnings_5y, 5)
        
        if self.cash_flow_a is not None and not self.cash_flow_a.empty:
            # FCF growth (Operating Cash Flow - CapEx)
            ocf_current = self._get_value(self.cash_flow_a, 'Operating Cash Flow', 0)
            capex_current = self._get_value(self.cash_flow_a, 'Capital Expenditure', 0)
            fcf_current = ocf_current + capex_current if ocf_current and capex_current else None  # CapEx is negative
            
            ocf_1y = self._get_value(self.cash_flow_a, 'Operating Cash Flow', 1)
            capex_1y = self._get_value(self.cash_flow_a, 'Capital Expenditure', 1)
            fcf_1y = ocf_1y + capex_1y if ocf_1y and capex_1y else None
            
            ocf_3y = self._get_value(self.cash_flow_a, 'Operating Cash Flow', 3)
            capex_3y = self._get_value(self.cash_flow_a, 'Capital Expenditure', 3)
            fcf_3y = ocf_3y + capex_3y if ocf_3y and capex_3y else None
            
            growth['fcf']['1y'] = self._calculate_growth_rate(fcf_current, fcf_1y)
            growth['fcf']['3y_cagr'] = self._calculate_cagr(fcf_current, fcf_3y, 3)
            growth['fcf']['current'] = fcf_current
        
        return growth
    
    def _calculate_cagr(self, current: Optional[float], past: Optional[float], years: int) -> Optional[float]:
        """Calculate Compound Annual Growth Rate"""
        if current is None or past is None or past == 0 or years == 0:
            return None
        try:
            return (((current / past) ** (1 / years)) - 1) * 100
        except (ValueError, ZeroDivisionError):
            return None
    
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
            ocf = self._get_value(self.cash_flow_a, 'Operating Cash Flow', 0)
            capex = self._get_value(self.cash_flow_a, 'Capital Expenditure', 0)
            
            if ocf and capex:
                fcf = ocf + capex  # CapEx is negative
                fcf_metrics['fcf'] = fcf
                
                # FCF Yield = FCF / Market Cap
                market_cap = self.info.get('market_cap')
                if market_cap:
                    fcf_metrics['fcf_yield'] = (fcf / market_cap) * 100
                
                # FCF per Share
                shares_outstanding = self.info.get('shares_outstanding') or self.info.get('sharesOutstanding')
                if shares_outstanding:
                    fcf_metrics['fcf_per_share'] = fcf / shares_outstanding
                
                # FCF Margin = FCF / Revenue
                revenue = self._get_value(self.income_stmt_a, 'Total Revenue', 0)
                if revenue:
                    fcf_metrics['fcf_margin'] = (fcf / revenue) * 100
        
        return fcf_metrics
    
    # ==================== Margin Analysis ====================
    
    def calculate_margins(self) -> Dict[str, Any]:
        """
        Calculate profitability margins with trends
        
        Returns:
            Dictionary with margin metrics and trends
        """
        margins = {
            'current': {},
            'trend': {}
        }
        
        if self.income_stmt_a is not None and not self.income_stmt_a.empty:
            # Get current period values
            revenue = self._get_value(self.income_stmt_a, 'Total Revenue', 0)
            gross_profit = self._get_value(self.income_stmt_a, 'Gross Profit', 0)
            operating_income = self._get_value(self.income_stmt_a, 'Operating Income', 0)
            ebitda = self._get_value(self.income_stmt_a, 'EBITDA', 0)
            net_income = self._get_value(self.income_stmt_a, 'Net Income', 0)
            
            # Current margins
            if revenue:
                if gross_profit:
                    margins['current']['gross_margin'] = (gross_profit / revenue) * 100
                if operating_income:
                    margins['current']['operating_margin'] = (operating_income / revenue) * 100
                if ebitda:
                    margins['current']['ebitda_margin'] = (ebitda / revenue) * 100
                if net_income:
                    margins['current']['net_margin'] = (net_income / revenue) * 100
            
            # Calculate trend (3-year average and direction)
            for i, period in enumerate(['current', '1y_ago', '2y_ago']):
                revenue_p = self._get_value(self.income_stmt_a, 'Total Revenue', i)
                net_income_p = self._get_value(self.income_stmt_a, 'Net Income', i)
                
                if revenue_p and net_income_p:
                    margin = (net_income_p / revenue_p) * 100
                    margins['trend'][period] = margin
        
        # Fallback to ticker.info
        if not margins['current']:
            if self.info.get('profit_margin'):
                margins['current']['net_margin'] = self.info['profit_margin'] * 100
            if self.info.get('operating_margin'):
                margins['current']['operating_margin'] = self.info['operating_margin'] * 100
        
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
            revenue = self._get_value(self.income_stmt_a, 'Total Revenue', 0)
            total_assets = self._get_value(self.balance_sheet_a, 'Total Assets', 0)
            efficiency['asset_turnover'] = self._safe_divide(revenue, total_assets)
            
            # Inventory Turnover = COGS / Average Inventory
            cogs = self._get_value(self.income_stmt_a, 'Cost Of Revenue', 0)
            inventory_current = self._get_value(self.balance_sheet_a, 'Inventory', 0)
            inventory_previous = self._get_value(self.balance_sheet_a, 'Inventory', 1)
            
            if inventory_current and inventory_previous:
                avg_inventory = (inventory_current + inventory_previous) / 2
                efficiency['inventory_turnover'] = self._safe_divide(cogs, avg_inventory)
                
                # Days Inventory Outstanding
                if efficiency['inventory_turnover']:
                    efficiency['days_inventory_outstanding'] = 365 / efficiency['inventory_turnover']
            
            # Receivables Turnover
            accounts_receivable = self._get_value(self.balance_sheet_a, 'Accounts Receivable', 0)
            accounts_receivable_prev = self._get_value(self.balance_sheet_a, 'Accounts Receivable', 1)
            
            if accounts_receivable and accounts_receivable_prev:
                avg_receivables = (accounts_receivable + accounts_receivable_prev) / 2
                efficiency['receivables_turnover'] = self._safe_divide(revenue, avg_receivables)
                
                # Days Sales Outstanding
                if efficiency['receivables_turnover']:
                    efficiency['days_sales_outstanding'] = 365 / efficiency['receivables_turnover']
            
            # Payables Turnover
            accounts_payable = self._get_value(self.balance_sheet_a, 'Accounts Payable', 0)
            accounts_payable_prev = self._get_value(self.balance_sheet_a, 'Accounts Payable', 1)
            
            if accounts_payable and accounts_payable_prev and cogs:
                avg_payables = (accounts_payable + accounts_payable_prev) / 2
                efficiency['payables_turnover'] = self._safe_divide(cogs, avg_payables)
                
                # Days Payable Outstanding
                if efficiency['payables_turnover']:
                    efficiency['days_payable_outstanding'] = 365 / efficiency['payables_turnover']
            
            # Cash Conversion Cycle
            dio = efficiency.get('days_inventory_outstanding')
            dso = efficiency.get('days_sales_outstanding')
            dpo = efficiency.get('days_payable_outstanding')
            
            if dio and dso and dpo:
                efficiency['cash_conversion_cycle'] = dio + dso - dpo
        
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
            net_income = self._get_value(self.income_stmt_a, 'Net Income', 0)
            revenue = self._get_value(self.income_stmt_a, 'Total Revenue', 0)
            total_assets = self._get_value(self.balance_sheet_a, 'Total Assets', 0)
            total_equity = self._get_value(self.balance_sheet_a, 'Stockholders Equity', 0)
            
            # Calculate components
            net_margin = self._safe_divide(net_income, revenue)
            asset_turnover = self._safe_divide(revenue, total_assets)
            equity_multiplier = self._safe_divide(total_assets, total_equity)
            
            if net_margin is not None:
                dupont['net_margin'] = net_margin * 100
            if asset_turnover is not None:
                dupont['asset_turnover'] = asset_turnover
            if equity_multiplier is not None:
                dupont['equity_multiplier'] = equity_multiplier
            
            # Calculate ROE
            if all(x is not None for x in [net_margin, asset_turnover, equity_multiplier]):
                # Type assertions after all() check
                assert net_margin is not None and asset_turnover is not None and equity_multiplier is not None
                dupont['roe_calculated'] = (net_margin * asset_turnover * equity_multiplier) * 100
            
            # Compare to reported ROE
            roe_reported = self.info.get('roe')
            if roe_reported:
                dupont['roe_reported'] = roe_reported * 100
        
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
            return None
        
        # Get balance sheet items
        current_assets = self._get_value(self.balance_sheet_a, 'Current Assets', 0)
        current_liabilities = self._get_value(self.balance_sheet_a, 'Current Liabilities', 0)
        total_assets = self._get_value(self.balance_sheet_a, 'Total Assets', 0)
        retained_earnings = self._get_value(self.balance_sheet_a, 'Retained Earnings', 0)
        total_liabilities = self._get_value(self.balance_sheet_a, 'Total Liabilities Net Minority Interest', 0)
        
        # Get income statement items
        ebit = self._get_value(self.income_stmt_a, 'EBIT', 0)
        revenue = self._get_value(self.income_stmt_a, 'Total Revenue', 0)
        
        # Get market cap
        market_cap = self.info.get('market_cap')
        
        # Calculate components
        if not all([current_assets, current_liabilities, total_assets, retained_earnings, 
                    total_liabilities, ebit, revenue, market_cap]):
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
        
        z_score = 1.2*x1 + 1.4*x2 + 3.3*x3 + 0.6*x4 + 1.0*x5
        
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
            return None
        
        score = 0
        
        # 1. Positive Net Income
        net_income = self._get_value(self.income_stmt_a, 'Net Income', 0)
        if net_income and net_income > 0:
            score += 1
        
        # 2. Positive Operating Cash Flow
        ocf = self._get_value(self.cash_flow_a, 'Operating Cash Flow', 0)
        if ocf and ocf > 0:
            score += 1
        
        # 3. ROA Increasing
        net_income_prev = self._get_value(self.income_stmt_a, 'Net Income', 1)
        total_assets = self._get_value(self.balance_sheet_a, 'Total Assets', 0)
        total_assets_prev = self._get_value(self.balance_sheet_a, 'Total Assets', 1)
        
        if net_income is not None and net_income_prev is not None and total_assets is not None and total_assets_prev is not None:
            roa_current = net_income / total_assets
            roa_prev = net_income_prev / total_assets_prev
            if roa_current > roa_prev:
                score += 1
        
        # 4. Quality of Earnings (OCF > Net Income)
        if ocf and net_income and ocf > net_income:
            score += 1
        
        # 5. Decreasing Long-Term Debt
        lt_debt = self._get_value(self.balance_sheet_a, 'Long Term Debt', 0)
        lt_debt_prev = self._get_value(self.balance_sheet_a, 'Long Term Debt', 1)
        if lt_debt is not None and lt_debt_prev is not None:
            if lt_debt < lt_debt_prev:
                score += 1
        
        # 6. Increasing Current Ratio
        current_assets = self._get_value(self.balance_sheet_a, 'Current Assets', 0)
        current_liabilities = self._get_value(self.balance_sheet_a, 'Current Liabilities', 0)
        current_assets_prev = self._get_value(self.balance_sheet_a, 'Current Assets', 1)
        current_liabilities_prev = self._get_value(self.balance_sheet_a, 'Current Liabilities', 1)
        
        if current_assets is not None and current_liabilities is not None and current_assets_prev is not None and current_liabilities_prev is not None:
            current_ratio = current_assets / current_liabilities
            current_ratio_prev = current_assets_prev / current_liabilities_prev
            if current_ratio > current_ratio_prev:
                score += 1
        
        # 7. No New Shares Issued
        shares = self.info.get('shares_outstanding') or self.info.get('sharesOutstanding')
        # This requires historical shares data which yfinance doesn't always provide
        # Skip for now or mark as N/A
        
        # 8. Increasing Gross Margin
        revenue = self._get_value(self.income_stmt_a, 'Total Revenue', 0)
        gross_profit = self._get_value(self.income_stmt_a, 'Gross Profit', 0)
        revenue_prev = self._get_value(self.income_stmt_a, 'Total Revenue', 1)
        gross_profit_prev = self._get_value(self.income_stmt_a, 'Gross Profit', 1)
        
        if revenue is not None and gross_profit is not None and revenue_prev is not None and gross_profit_prev is not None:
            gross_margin = gross_profit / revenue
            gross_margin_prev = gross_profit_prev / revenue_prev
            if gross_margin > gross_margin_prev:
                score += 1
        
        # 9. Increasing Asset Turnover
        if revenue is not None and total_assets is not None:
            # revenue_prev and total_assets_prev already exist from earlier checks
            revenue_prev_at = self._get_value(self.income_stmt_a, 'Total Revenue', 1)  # Get again to be safe
            total_assets_prev_at = self._get_value(self.balance_sheet_a, 'Total Assets', 1)
            if revenue_prev_at is not None and total_assets_prev_at is not None:
                asset_turnover = revenue / total_assets
                asset_turnover_prev = revenue_prev_at / total_assets_prev_at
                if asset_turnover > asset_turnover_prev:
                    score += 1
        
        return score
    
    # ==================== Aggregation Methods ====================
    
    def calculate_all(self) -> Dict[str, Any]:
        """
        Calculate all fundamental metrics
        
        Returns:
            Dictionary with all analysis results
        """
        logger.info("Calculating fundamental metrics...")
        
        results = {
            'growth_rates': self.calculate_growth_rates(),
            'fcf_metrics': self.calculate_fcf_metrics(),
            'margins': self.calculate_margins(),
            'efficiency': self.calculate_efficiency_ratios(),
            'dupont': self.calculate_dupont_analysis(),
            'quality_scores': {
                'altman_z': self.calculate_altman_z_score(),
                'piotroski_f': self.calculate_piotroski_f_score()
            }
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
            'ticker': self.info.get('symbol'),
            'company_name': self.info.get('name'),
            'sector': self.info.get('sector'),
            'industry': self.info.get('industry'),
            'analysis': self.calculate_all()
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
        growth = results['growth_rates']
        
        if any(growth.values()):
            md.append("| Metric | 1 Year | 3 Year CAGR | 5 Year CAGR |")
            md.append("|--------|--------|--------------|--------------|")
            
            revenue = growth.get('revenue', {})
            md.append(f"| Revenue | {self._format_pct(revenue.get('1y'))} | "
                     f"{self._format_pct(revenue.get('3y_cagr'))} | "
                     f"{self._format_pct(revenue.get('5y_cagr'))} |")
            
            earnings = growth.get('earnings', {})
            md.append(f"| Earnings | {self._format_pct(earnings.get('1y'))} | "
                     f"{self._format_pct(earnings.get('3y_cagr'))} | "
                     f"{self._format_pct(earnings.get('5y_cagr'))} |")
            
            fcf = growth.get('fcf', {})
            md.append(f"| Free Cash Flow | {self._format_pct(fcf.get('1y'))} | "
                     f"{self._format_pct(fcf.get('3y_cagr'))} | N/A |")
            md.append("")
        else:
            md.append("*Insufficient historical data for growth analysis*")
            md.append("")
        
        # Free Cash Flow Metrics
        md.append("### Free Cash Flow Analysis")
        md.append("")
        fcf_metrics = results['fcf_metrics']
        
        if fcf_metrics:
            md.append("| Metric | Value |")
            md.append("|--------|-------|")
            
            if fcf_metrics.get('fcf'):
                md.append(f"| Free Cash Flow | ${fcf_metrics['fcf']:,.0f} |")
            if fcf_metrics.get('fcf_yield'):
                md.append(f"| FCF Yield | {fcf_metrics['fcf_yield']:.2f}% |")
            if fcf_metrics.get('fcf_per_share'):
                md.append(f"| FCF per Share | ${fcf_metrics['fcf_per_share']:.2f} |")
            if fcf_metrics.get('fcf_margin'):
                md.append(f"| FCF Margin | {fcf_metrics['fcf_margin']:.2f}% |")
            md.append("")
        else:
            md.append("*FCF data unavailable*")
            md.append("")
        
        # Profitability Margins
        md.append("### Profitability Margins")
        md.append("")
        margins = results['margins']
        
        if margins.get('current'):
            md.append("| Margin Type | Current |")
            md.append("|-------------|---------|")
            
            current = margins['current']
            if current.get('gross_margin'):
                md.append(f"| Gross Margin | {current['gross_margin']:.2f}% |")
            if current.get('ebitda_margin'):
                md.append(f"| EBITDA Margin | {current['ebitda_margin']:.2f}% |")
            if current.get('operating_margin'):
                md.append(f"| Operating Margin | {current['operating_margin']:.2f}% |")
            if current.get('net_margin'):
                md.append(f"| Net Margin | {current['net_margin']:.2f}% |")
            md.append("")
            
            # Margin trend
            trend = margins.get('trend', {})
            if len(trend) >= 2:
                current_margin = trend.get('current')
                prev_margin = trend.get('1y_ago')
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
        efficiency = results['efficiency']
        
        if efficiency:
            md.append("| Ratio | Value |")
            md.append("|-------|-------|")
            
            if efficiency.get('asset_turnover'):
                md.append(f"| Asset Turnover | {efficiency['asset_turnover']:.2f}x |")
            if efficiency.get('inventory_turnover'):
                md.append(f"| Inventory Turnover | {efficiency['inventory_turnover']:.2f}x |")
            if efficiency.get('days_inventory_outstanding'):
                md.append(f"| Days Inventory Outstanding | {efficiency['days_inventory_outstanding']:.0f} days |")
            if efficiency.get('receivables_turnover'):
                md.append(f"| Receivables Turnover | {efficiency['receivables_turnover']:.2f}x |")
            if efficiency.get('days_sales_outstanding'):
                md.append(f"| Days Sales Outstanding | {efficiency['days_sales_outstanding']:.0f} days |")
            if efficiency.get('cash_conversion_cycle'):
                md.append(f"| Cash Conversion Cycle | {efficiency['cash_conversion_cycle']:.0f} days |")
            md.append("")
        else:
            md.append("*Efficiency data unavailable*")
            md.append("")
        
        # DuPont Analysis
        md.append("### DuPont ROE Analysis")
        md.append("")
        dupont = results['dupont']
        
        if dupont:
            md.append("| Component | Value |")
            md.append("|-----------|-------|")
            
            if dupont.get('net_margin'):
                md.append(f"| Net Margin | {dupont['net_margin']:.2f}% |")
            if dupont.get('asset_turnover'):
                md.append(f"| Asset Turnover | {dupont['asset_turnover']:.2f}x |")
            if dupont.get('equity_multiplier'):
                md.append(f"| Equity Multiplier | {dupont['equity_multiplier']:.2f}x |")
            if dupont.get('roe_calculated'):
                md.append(f"| **ROE (Calculated)** | **{dupont['roe_calculated']:.2f}%** |")
            if dupont.get('roe_reported'):
                md.append(f"| ROE (Reported) | {dupont['roe_reported']:.2f}% |")
            md.append("")
            md.append("*ROE = Net Margin × Asset Turnover × Equity Multiplier*")
            md.append("")
        else:
            md.append("*DuPont analysis unavailable*")
            md.append("")
        
        # Quality Scores
        md.append("### Quality Scores")
        md.append("")
        quality = results['quality_scores']
        
        md.append("| Score | Value | Interpretation |")
        md.append("|-------|-------|----------------|")
        
        # Altman Z-Score
        z_score = quality.get('altman_z')
        if z_score:
            if z_score > 2.99:
                z_interp = "Safe Zone"
            elif z_score > 1.81:
                z_interp = "Grey Zone"
            else:
                z_interp = "Distress Zone"
            md.append(f"| Altman Z-Score | {z_score:.2f} | {z_interp} |")
        else:
            md.append("| Altman Z-Score | N/A | Insufficient data |")
        
        # Piotroski F-Score
        f_score = quality.get('piotroski_f')
        if f_score is not None:
            if f_score >= 8:
                f_interp = "Strong"
            elif f_score >= 5:
                f_interp = "Average"
            else:
                f_interp = "Weak"
            md.append(f"| Piotroski F-Score | {f_score}/9 | {f_interp} |")
        else:
            md.append("| Piotroski F-Score | N/A | Insufficient data |")
        
        md.append("")
        
        return md
    
    def _format_pct(self, value: Optional[float]) -> str:
        """Format percentage value for display"""
        if value is None:
            return "N/A"
        return f"{value:+.2f}%"


def analyze_fundamentals(
    ticker_info: Dict[str, Any],
    fundamentals: Dict[str, pd.DataFrame],
    price_data: Optional[pd.DataFrame] = None
) -> Dict[str, Any]:
    """
    Convenience function for fundamental analysis
    
    Args:
        ticker_info: Dictionary from yfinance ticker.info
        fundamentals: Dictionary with financial statements
        price_data: Historical price data
        
    Returns:
        Complete fundamental analysis summary
    """
    analyzer = FundamentalAnalyzer(ticker_info, fundamentals, price_data)
    return analyzer.get_summary()
