"""
Valuation Analysis Module
Performs intrinsic value estimation and dividend/earnings analysis
"""

import logging
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from ..utils.dataframe_utils import normalize_datetime_index, safe_get_dataframe_value
from ..utils.financial import calculate_cagr, to_float

logger = logging.getLogger(__name__)


class ValuationAnalyzer:
    """
    Performs valuation analysis for equities

    Capabilities:
    - DCF (Discounted Cash Flow) valuation
    - DDM (Dividend Discount Model) valuation
    - Dividend analysis (yield, growth, coverage, sustainability)
    - Earnings analysis (EPS trends, surprises, quality)
    - Fair value vs current price comparison
    """

    def __init__(
        self,
        ticker: str,
        ticker_info: Dict[str, Any],
        price_data: Optional[pd.DataFrame] = None,
        fundamentals: Optional[Dict[str, pd.DataFrame]] = None,
        earnings_data: Optional[Dict[str, pd.DataFrame]] = None,
        dividends_data: Optional[pd.Series] = None,
    ):
        """
        Initialize valuation analyzer

        Args:
            ticker: Stock ticker symbol
            ticker_info: Dictionary from yfinance ticker.info
            price_data: Historical price data
            fundamentals: Financial statements (income_stmt, balance_sheet, cash_flow)
            earnings_data: Earnings history and dates
            dividends_data: Historical dividend payments
        """
        self.ticker = ticker
        self.info = ticker_info
        self.price_data = price_data
        self.fundamentals = fundamentals or {}
        self.earnings_data = earnings_data or {}
        self.dividends_data = dividends_data

        # Extract currency (default to USD if not specified)
        self.currency = ticker_info.get("currency", "USD")

        # Extract current price
        self.current_price = to_float(ticker_info.get("currentPrice"))
        if (
            (self.current_price is None or self.current_price == 0.0)
            and price_data is not None
            and not price_data.empty
        ):
            self.current_price = to_float(price_data["Close"].iloc[-1])

    # ==================== Helper Methods ====================

    def _get_info_value(self, key: str) -> Optional[float]:
        """
        Get value from ticker info, trying both camelCase and snake_case keys

        Args:
            key: Key to look up (in camelCase)

        Returns:
            Float value or None if not found
        """
        # Try camelCase first
        value = to_float(self.info.get(key))
        if value and value > 0:
            return value

        # Try snake_case conversion
        # Convert camelCase to snake_case (e.g., dividendYield -> dividend_yield)
        import re

        snake_key = re.sub(r"(?<!^)(?=[A-Z])", "_", key).lower()
        value = to_float(self.info.get(snake_key))
        return value if value and value > 0 else None

    def _get_value(
        self, df: Optional[pd.DataFrame], row_name: str, col_index: int = 0
    ) -> Optional[float]:
        """Safely extract value from financial statement DataFrame"""
        return safe_get_dataframe_value(df, row_name, col_index)

    def _calculate_cagr(
        self, ending_value: float, beginning_value: float, num_periods: int
    ) -> Optional[float]:
        """Calculate Compound Annual Growth Rate"""
        result = calculate_cagr(ending_value, beginning_value, num_periods)
        return result if result != 0.0 else None

    def _get_dividend_frequency(self, dividends_series: pd.Series) -> str:
        """
        Detect dividend payment frequency based on time between payments

        Returns:
            Frequency type: 'annual', 'semi-annual', 'quarterly', 'monthly', or 'irregular'
        """
        if len(dividends_series) < 2:
            return "unknown"

        # Calculate median time between payments (in days)
        # Convert index to series, diff gives Timedelta objects
        time_diffs = pd.Series(dividends_series.index).diff()
        median_timedelta = time_diffs.median()

        if pd.isna(median_timedelta):
            return "unknown"

        # Convert Timedelta to days - handle both Timedelta and numeric types
        median_days: int
        if isinstance(median_timedelta, pd.Timedelta):
            median_days = median_timedelta.days
        else:
            # Fallback to 90 if we can't determine (shouldn't happen with proper datetime index)
            median_days = 90

        # Classify based on median interval
        if median_days > 300:  # ~365 days
            return "annual"
        elif median_days > 150:  # ~180 days
            return "semi-annual"
        elif median_days > 60:  # ~90 days
            return "quarterly"
        elif median_days > 20:  # ~30 days
            return "monthly"
        else:
            return "irregular"

    def _calculate_ttm_dividend(self, dividends_series: pd.Series) -> float:
        """
        Calculate trailing 12-month dividend intelligently based on payment frequency

        Handles annual, semi-annual, quarterly, monthly, and irregular payment schedules

        Args:
            dividends_series: Dividend Series with DatetimeIndex

        Returns:
            TTM dividend amount
        """
        if dividends_series.empty:
            return 0.0

        # Normalize to timezone-naive for consistent comparisons
        dividends_series = normalize_datetime_index(dividends_series)

        # Detect payment frequency
        frequency = self._get_dividend_frequency(dividends_series)

        # Try time-based filtering first (last 12 months)
        now = pd.Timestamp.now()
        one_year_ago = now - pd.DateOffset(months=12)
        ttm_dividends = dividends_series[dividends_series.index >= one_year_ago]

        # If we got dividends in the TTM window, use them
        if not ttm_dividends.empty and ttm_dividends.sum() > 0:
            return ttm_dividends.sum()

        # Fallback: use appropriate number of payments based on frequency
        if frequency == "annual":
            # For annual payers, most recent single payment represents the annual dividend
            return dividends_series.tail(1).sum()
        elif frequency == "semi-annual":
            # Last 2 payments = 1 year
            return dividends_series.tail(2).sum()
        elif frequency == "quarterly":
            # Last 4 payments = 1 year
            return dividends_series.tail(4).sum()
        elif frequency == "monthly":
            # Last 12 payments = 1 year
            return dividends_series.tail(12).sum()
        else:
            # For irregular/unknown, use last 4 payments as conservative estimate
            return dividends_series.tail(min(4, len(dividends_series))).sum()

    # ==================== DCF Valuation ====================

    def calculate_dcf_valuation(
        self,
        growth_rate: Optional[float] = None,
        terminal_growth_rate: float = 2.5,
        wacc: Optional[float] = None,
        projection_years: int = 5,
    ) -> Dict[str, Any]:
        """
        Calculate DCF (Discounted Cash Flow) intrinsic value

        Args:
            growth_rate: FCF growth rate (%). If None, calculated from historical data
            terminal_growth_rate: Perpetual growth rate (%). Default 2.5%
            wacc: Weighted Average Cost of Capital (%). If None, estimated from beta/market
            projection_years: Number of years to project cash flows

        Returns:
            Dictionary with DCF valuation results
        """
        result = {
            "intrinsic_value_per_share": None,
            "current_price": self.current_price,
            "currency": self.currency,
            "discount_premium_pct": None,
            "fcf_current": None,
            "growth_rate_used": None,
            "terminal_growth_rate": terminal_growth_rate,
            "wacc_used": None,
            "enterprise_value": None,
            "equity_value": None,
            "shares_outstanding": None,
            "projection_years": projection_years,
            "assumptions": {},
            "error": None,
        }

        try:
            # Get cash flow data
            cash_flow_a = self.fundamentals.get("income_stmt_annual")
            if cash_flow_a is None or cash_flow_a.empty:
                result["error"] = "No annual cash flow data available"
                return result

            # Get current FCF directly (yfinance provides it pre-calculated)
            fcf_current = self._get_value(
                self.fundamentals.get("cash_flow_annual"), "Free Cash Flow", 0
            )

            if fcf_current is None:
                result["error"] = "Free Cash Flow not available"
                return result
            result["fcf_current"] = fcf_current

            if fcf_current <= 0:
                result["error"] = "Negative or zero FCF - DCF not applicable"
                return result

            # Estimate growth rate if not provided
            if growth_rate is None:
                growth_rate = self._estimate_fcf_growth_rate()
                if growth_rate is None:
                    growth_rate = 5.0  # Default conservative growth
                result["assumptions"]["growth_rate_source"] = "historical_fcf"
            else:
                result["assumptions"]["growth_rate_source"] = "user_provided"

            result["growth_rate_used"] = growth_rate

            # Estimate WACC if not provided
            if wacc is None:
                wacc = self._estimate_wacc()
                result["assumptions"]["wacc_source"] = "estimated_from_beta"
            else:
                result["assumptions"]["wacc_source"] = "user_provided"

            result["wacc_used"] = wacc

            # Validate WACC > terminal growth (required for Gordon Growth Model)
            if wacc <= terminal_growth_rate:
                result["error"] = (
                    f"WACC ({wacc:.2f}%) must exceed terminal growth "
                    f"({terminal_growth_rate:.2f}%) for DCF calculation"
                )
                return result

            # Project FCF for projection_years
            projected_fcf = []
            for year in range(1, projection_years + 1):
                fcf_year = fcf_current * pow(1 + growth_rate / 100, year)
                pv_fcf = fcf_year / pow(1 + wacc / 100, year)
                projected_fcf.append({"year": year, "fcf": fcf_year, "present_value": pv_fcf})

            # Calculate terminal value
            fcf_terminal_year = fcf_current * pow(1 + growth_rate / 100, projection_years)
            fcf_terminal = fcf_terminal_year * (1 + terminal_growth_rate / 100)
            terminal_value = fcf_terminal / ((wacc - terminal_growth_rate) / 100)
            pv_terminal_value = terminal_value / pow(1 + wacc / 100, projection_years)

            # Enterprise Value = Sum of PV of projected FCF + PV of terminal value
            pv_projected_fcf = sum(cf["present_value"] for cf in projected_fcf)
            enterprise_value = pv_projected_fcf + pv_terminal_value
            result["enterprise_value"] = enterprise_value
            result["assumptions"]["pv_projected_fcf"] = pv_projected_fcf
            result["assumptions"]["terminal_value"] = terminal_value
            result["assumptions"]["pv_terminal_value"] = pv_terminal_value

            # Convert to Equity Value (EV - Net Debt)
            cash = self._get_info_value("totalCash") or 0.0
            debt = self._get_info_value("totalDebt") or 0.0
            net_debt = debt - cash
            equity_value = enterprise_value - net_debt
            result["equity_value"] = equity_value
            result["assumptions"]["cash"] = cash
            result["assumptions"]["debt"] = debt
            result["assumptions"]["net_debt"] = net_debt

            # Per-share intrinsic value
            shares_outstanding = to_float(self.info.get("sharesOutstanding")) or to_float(
                self.info.get("impliedSharesOutstanding")
            )

            # Fallback: calculate from market cap and current price
            if not shares_outstanding or shares_outstanding <= 0:
                market_cap = self._get_info_value("marketCap")
                if market_cap and market_cap > 0 and self.current_price and self.current_price > 0:
                    shares_outstanding = market_cap / self.current_price
                    result["assumptions"]["shares_calculated_from_market_cap"] = True

            if shares_outstanding and shares_outstanding > 0:
                result["shares_outstanding"] = shares_outstanding
                intrinsic_value = equity_value / shares_outstanding
                result["intrinsic_value_per_share"] = intrinsic_value

                # Calculate discount/premium
                if self.current_price and self.current_price > 0:
                    discount_premium = (
                        (self.current_price - intrinsic_value) / intrinsic_value
                    ) * 100
                    result["discount_premium_pct"] = discount_premium
            else:
                result["error"] = "Shares outstanding not available"

        except Exception as e:
            logger.error(f"DCF calculation error for {self.ticker}: {e}")
            result["error"] = str(e)

        return result

    def _estimate_fcf_growth_rate(self) -> Optional[float]:
        """Estimate FCF growth rate from historical cash flow data"""
        try:
            cash_flow_a = self.fundamentals.get("cash_flow_annual")
            if cash_flow_a is None or cash_flow_a.empty:
                return None

            # Get 3-year historical FCF
            fcf_values = []
            for i in range(3):
                fcf = self._get_value(cash_flow_a, "Free Cash Flow", i)
                if fcf is not None:
                    fcf_values.append(fcf)

            if len(fcf_values) >= 2 and fcf_values[-1] > 0:
                return self._calculate_cagr(fcf_values[0], fcf_values[-1], len(fcf_values) - 1)

        except Exception as e:
            logger.warning(f"Could not estimate FCF growth rate: {e}")

        return None

    def _estimate_wacc(self) -> float:
        """
        Estimate WACC using CAPM

        WACC ≈ Cost of Equity (for simplicity, ignoring debt component)
        Cost of Equity = Risk-free rate + Beta * Market risk premium
        """
        risk_free_rate = 4.0  # 4% assumption (could pull from config)
        market_risk_premium = 8.0  # Historical equity risk premium

        beta = self._get_info_value("beta")
        if beta is None or beta <= 0:
            beta = 1.0  # Market beta if not available

        cost_of_equity = risk_free_rate + (beta * market_risk_premium)

        # For simplicity, using cost of equity as WACC proxy
        # More sophisticated: weight by debt-to-equity ratio
        return cost_of_equity

    # ==================== Dividend Discount Model ====================

    def calculate_ddm_valuation(
        self, growth_rate: Optional[float] = None, required_return: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Calculate DDM (Dividend Discount Model) intrinsic value using Gordon Growth Model

        Formula: Intrinsic Value = D1 / (r - g)
        where D1 = next year's dividend, r = required return, g = dividend growth rate

        Args:
            growth_rate: Dividend growth rate (%). If None, calculated from history
            required_return: Required rate of return (%). If None, estimated from CAPM

        Returns:
            Dictionary with DDM valuation results
        """
        result = {
            "intrinsic_value_per_share": None,
            "current_price": self.current_price,
            "currency": self.currency,
            "discount_premium_pct": None,
            "current_dividend": None,
            "next_dividend_estimate": None,
            "growth_rate_used": None,
            "required_return_used": None,
            "model": "Gordon Growth Model",
            "assumptions": {},
            "error": None,
        }

        try:
            # Check if stock pays dividends (check actual data first)
            if self.dividends_data is None or self.dividends_data.empty:
                result["error"] = "No dividend history available"
                return result

            # Verify dividends exist
            if self.dividends_data.sum() <= 0:
                result["error"] = "Stock does not pay dividends - DDM not applicable"
                return result

            # Normalize to timezone-naive DatetimeIndex for consistent handling
            dividends_series = normalize_datetime_index(self.dividends_data)

            # Calculate trailing 12-month dividend (frequency-aware)
            ttm_dividend = self._calculate_ttm_dividend(dividends_series)
            if ttm_dividend <= 0:
                result["error"] = "No dividends paid in trailing 12 months"
                return result

            result["current_dividend"] = ttm_dividend

            # Estimate growth rate if not provided
            if growth_rate is None:
                growth_rate = self._estimate_dividend_growth_rate()
                if growth_rate is None:
                    growth_rate = 3.0  # Default conservative growth
                result["assumptions"]["growth_rate_source"] = "historical_dividends"
            else:
                result["assumptions"]["growth_rate_source"] = "user_provided"

            result["growth_rate_used"] = growth_rate

            # Estimate required return if not provided
            if required_return is None:
                required_return = self._estimate_wacc()
                result["assumptions"]["required_return_source"] = "estimated_from_beta"
            else:
                result["assumptions"]["required_return_source"] = "user_provided"

            result["required_return_used"] = required_return

            # Validate required return > growth rate
            if required_return <= growth_rate:
                result["error"] = (
                    f"Required return ({required_return:.2f}%) must exceed "
                    f"dividend growth ({growth_rate:.2f}%) for DDM calculation"
                )
                return result

            # Calculate next year's dividend
            d1 = ttm_dividend * (1 + growth_rate / 100)
            result["next_dividend_estimate"] = d1

            # Gordon Growth Model: V = D1 / (r - g)
            intrinsic_value = d1 / ((required_return - growth_rate) / 100)
            result["intrinsic_value_per_share"] = intrinsic_value

            # Calculate discount/premium
            if self.current_price and self.current_price > 0:
                discount_premium = ((self.current_price - intrinsic_value) / intrinsic_value) * 100
                result["discount_premium_pct"] = discount_premium

        except Exception as e:
            logger.error(f"DDM calculation error for {self.ticker}: {e}")
            result["error"] = str(e)

        return result

    def _estimate_dividend_growth_rate(self) -> Optional[float]:
        """Estimate dividend growth rate from historical data"""
        try:
            if self.dividends_data is None or self.dividends_data.empty:
                return None

            # Normalize to timezone-naive DatetimeIndex for consistent handling
            dividends_series = normalize_datetime_index(self.dividends_data)

            # Get annual dividend totals for past years
            annual_dividends = dividends_series.resample("YE").sum()
            annual_dividends = annual_dividends[annual_dividends > 0]

            if len(annual_dividends) < 2:
                return None

            # Use last 3-5 years if available
            years_to_use = min(5, len(annual_dividends))
            recent_dividends = annual_dividends.tail(years_to_use)

            if len(recent_dividends) >= 2:
                return self._calculate_cagr(
                    recent_dividends.iloc[-1], recent_dividends.iloc[0], len(recent_dividends) - 1
                )

        except Exception as e:
            logger.warning(f"Could not estimate dividend growth rate: {e}")

        return None

    # ==================== Dividend Analysis ====================

    def analyze_dividends(self) -> Dict[str, Any]:
        """
        Comprehensive dividend analysis

        Returns:
            Dictionary with dividend metrics and sustainability analysis
        """
        result = {
            "pays_dividends": False,
            "dividend_yield": None,
            "annual_dividend": None,
            "payout_ratio": None,
            "dividend_growth_rate": None,
            "dividend_coverage_ratio": None,
            "consecutive_years": None,
            "latest_ex_dividend_date": None,
            "sustainability_score": None,
            "sustainability_rating": None,
            "warnings": [],
        }

        try:
            # Check if dividends are paid (check both info and actual dividend data)
            dividend_yield = self._get_info_value("dividendYield")
            has_dividend_data = (
                self.dividends_data is not None
                and not self.dividends_data.empty
                and self.dividends_data.sum() > 0
            )

            if not has_dividend_data and (not dividend_yield or dividend_yield <= 0):
                return result

            result["pays_dividends"] = True

            if dividend_yield and dividend_yield > 0:
                # dividend_yield might be stored as percentage (3.66) or decimal (0.0366)
                # If value > 1, it's already a percentage
                result["dividend_yield"] = (
                    dividend_yield if dividend_yield > 1 else dividend_yield * 100
                )

            # Get TTM dividend
            if has_dividend_data and self.dividends_data is not None:
                # Normalize to timezone-naive DatetimeIndex for consistent handling
                dividends_series = normalize_datetime_index(self.dividends_data)

                # Calculate TTM dividend (frequency-aware)
                ttm_dividend = self._calculate_ttm_dividend(dividends_series)
                result["annual_dividend"] = ttm_dividend

                # Calculate growth rate
                growth_rate = self._estimate_dividend_growth_rate()
                result["dividend_growth_rate"] = growth_rate

                # Count consecutive years of dividend payments
                annual_divs = dividends_series.resample("YE").sum()
                consecutive = 0
                for div in reversed(annual_divs.values):
                    if div is not None and div > 0:
                        consecutive += 1
                    else:
                        break
                result["consecutive_years"] = consecutive

                # Latest ex-dividend date
                result["latest_ex_dividend_date"] = str(dividends_series.index[-1])

            # Payout ratio
            payout_ratio = self._get_info_value("payoutRatio")
            result["payout_ratio"] = payout_ratio * 100 if payout_ratio else None

            # Dividend coverage ratio (inverse of payout ratio)
            # Coverage = Earnings / Dividends
            if payout_ratio and payout_ratio > 0:
                coverage = 1 / payout_ratio
                result["dividend_coverage_ratio"] = coverage

                # Sustainability warnings
                if payout_ratio > 1.0:
                    result["warnings"].append(
                        "Payout ratio > 100% - dividends exceed earnings (unsustainable)"
                    )
                elif payout_ratio > 0.8:
                    result["warnings"].append("High payout ratio (>80%) - limited room for growth")
                elif coverage < 1.5:
                    result["warnings"].append(
                        "Low dividend coverage (<1.5x) - risk of dividend cut"
                    )

            # Sustainability score (0-100)
            score = self._calculate_dividend_sustainability_score(result)
            result["sustainability_score"] = score

            # Rating interpretation
            if score >= 80:
                result["sustainability_rating"] = "Excellent"
            elif score >= 60:
                result["sustainability_rating"] = "Good"
            elif score >= 40:
                result["sustainability_rating"] = "Fair"
            elif score >= 20:
                result["sustainability_rating"] = "Poor"
            else:
                result["sustainability_rating"] = "High Risk"

        except Exception as e:
            logger.error(f"Dividend analysis error for {self.ticker}: {e}")
            result["error"] = str(e)

        return result

    def _calculate_dividend_sustainability_score(self, dividend_data: Dict[str, Any]) -> int:
        """Calculate 0-100 sustainability score based on dividend metrics"""
        score = 0

        # Payout ratio component (40 points)
        payout = dividend_data.get("payout_ratio")
        if payout is not None:
            if payout <= 50:
                score += 40
            elif payout <= 70:
                score += 30
            elif payout <= 90:
                score += 15
            elif payout <= 100:
                score += 5

        # Growth rate component (30 points)
        growth = dividend_data.get("dividend_growth_rate")
        if growth is not None:
            if growth >= 10:
                score += 30
            elif growth >= 5:
                score += 20
            elif growth >= 0:
                score += 10

        # Consistency component (30 points)
        consecutive = dividend_data.get("consecutive_years") or 0
        if consecutive >= 10:
            score += 30
        elif consecutive >= 5:
            score += 20
        elif consecutive >= 3:
            score += 10
        elif consecutive >= 1:
            score += 5

        return score

    # ==================== Earnings Analysis ====================

    def analyze_earnings(self) -> Dict[str, Any]:
        """
        Comprehensive earnings analysis

        Returns:
            Dictionary with EPS trends, surprises, and quality metrics
        """
        result = {
            "current_eps": None,
            "forward_eps": None,
            "eps_growth_1y": None,
            "eps_growth_3y_cagr": None,
            "next_earnings_date": None,
            "next_earnings_estimate": None,
            "recent_surprises": [],
            "surprise_stats": {},
            "earnings_quality": {},
            "trend": None,
        }

        try:
            # Calculate current TTM EPS from recent quarterly earnings
            earnings_history = self.earnings_data.get("earnings_history")
            if earnings_history is not None and not earnings_history.empty:
                # Sum last 4 quarters for TTM EPS
                recent_eps = earnings_history.tail(4)
                if len(recent_eps) == 4:
                    ttm_eps = sum(
                        to_float(row.get("epsActual", 0)) for _, row in recent_eps.iterrows()
                    )
                    if ttm_eps > 0:
                        result["current_eps"] = ttm_eps

            # Try to get forward EPS from info (may not exist)
            eps_forward = self._get_info_value("forwardEps")
            result["forward_eps"] = eps_forward

            # Earnings history analysis
            if earnings_history is not None and not earnings_history.empty:
                # Extract recent surprises
                recent = earnings_history.tail(4)
                for _, row in recent.iterrows():
                    surprise = {
                        "quarter": str(row.get("quarter", "")),
                        "eps_actual": to_float(row.get("epsActual")),
                        "eps_estimate": to_float(row.get("epsEstimate")),
                        "surprise_pct": to_float(row.get("surprisePercent", 0)) * 100,
                    }
                    result["recent_surprises"].append(surprise)

                # Surprise statistics
                if len(result["recent_surprises"]) > 0:
                    surprises = [s["surprise_pct"] for s in result["recent_surprises"]]
                    result["surprise_stats"] = {
                        "avg_surprise_pct": np.mean(surprises),
                        "positive_surprises": sum(1 for s in surprises if s > 0),
                        "negative_surprises": sum(1 for s in surprises if s < 0),
                        "beat_rate": sum(1 for s in surprises if s > 0) / len(surprises) * 100,
                    }

            # Next earnings date
            earnings_dates = self.earnings_data.get("earnings_dates")
            if earnings_dates is not None and not earnings_dates.empty:
                # Find next upcoming date
                try:
                    # Ensure index is DatetimeIndex
                    if not isinstance(earnings_dates.index, pd.DatetimeIndex):
                        earnings_dates.index = pd.to_datetime(earnings_dates.index)

                    now = pd.Timestamp.now()
                    upcoming = earnings_dates[earnings_dates.index > now]
                    if not upcoming.empty:
                        next_date = upcoming.index[0]
                        result["next_earnings_date"] = str(next_date)
                        result["next_earnings_estimate"] = to_float(
                            upcoming.iloc[0].get("EPS Estimate")
                        )
                except Exception as e:
                    logger.warning(f"Could not parse earnings dates: {e}")

            # EPS growth calculation
            income_stmt = self.fundamentals.get("income_stmt_annual")
            if income_stmt is not None and not income_stmt.empty:
                eps_current = self._get_value(income_stmt, "Diluted EPS", 0) or self._get_value(
                    income_stmt, "Basic EPS", 0
                )
                eps_1y = self._get_value(income_stmt, "Diluted EPS", 1) or self._get_value(
                    income_stmt, "Basic EPS", 1
                )
                eps_3y = self._get_value(income_stmt, "Diluted EPS", 3) or self._get_value(
                    income_stmt, "Basic EPS", 3
                )

                if eps_current and eps_1y and eps_1y != 0:
                    result["eps_growth_1y"] = ((eps_current - eps_1y) / abs(eps_1y)) * 100

                if eps_current and eps_3y and eps_3y > 0:
                    result["eps_growth_3y_cagr"] = self._calculate_cagr(eps_current, eps_3y, 3)

            # Trend determination
            if result["eps_growth_1y"]:
                if result["eps_growth_1y"] > 10:
                    result["trend"] = "Strong Growth"
                elif result["eps_growth_1y"] > 0:
                    result["trend"] = "Moderate Growth"
                elif result["eps_growth_1y"] > -10:
                    result["trend"] = "Slight Decline"
                else:
                    result["trend"] = "Declining"

            # Earnings quality metrics
            result["earnings_quality"] = self._assess_earnings_quality()

        except Exception as e:
            logger.error(f"Earnings analysis error for {self.ticker}: {e}")
            result["error"] = str(e)

        return result

    def _assess_earnings_quality(self) -> Dict[str, Any]:
        """
        Assess earnings quality based on cash flow vs net income

        High-quality earnings are backed by cash flow
        """
        quality = {"assessment": None, "score": None, "metrics": {}}

        try:
            income_stmt = self.fundamentals.get("income_stmt_annual")
            cash_flow = self.fundamentals.get("cash_flow_annual")

            if income_stmt is None or cash_flow is None:
                return quality

            if income_stmt.empty or cash_flow.empty:
                return quality

            net_income = self._get_value(income_stmt, "Net Income", 0)

            # Try multiple field names for operating cash flow
            ocf = None
            ocf_field_names = [
                "Operating Cash Flow",
                "Cash From Operating Activities",
                "Cash Flowsfromusedin Operating Activities Direct",
                "Total Cash From Operating Activities",
                "Net Cash Provided By Operating Activities",
            ]
            for field_name in ocf_field_names:
                ocf = self._get_value(cash_flow, field_name, 0)
                if ocf is not None and ocf != 0:
                    break

            if net_income and ocf and net_income > 0:
                # Cash flow to net income ratio
                cf_to_ni_ratio = ocf / net_income
                quality["metrics"]["cash_flow_to_earnings_ratio"] = cf_to_ni_ratio

                # Accruals (Net Income - OCF)
                accruals = net_income - ocf
                accruals_pct = (accruals / net_income) * 100
                quality["metrics"]["accruals_pct"] = accruals_pct

                # Score based on ratio
                if cf_to_ni_ratio >= 1.2:
                    quality["score"] = 90
                    quality["assessment"] = "High Quality (strong cash backing)"
                elif cf_to_ni_ratio >= 1.0:
                    quality["score"] = 75
                    quality["assessment"] = "Good Quality (cash flow matches earnings)"
                elif cf_to_ni_ratio >= 0.8:
                    quality["score"] = 50
                    quality["assessment"] = "Fair Quality (moderate cash backing)"
                else:
                    quality["score"] = 25
                    quality["assessment"] = "Low Quality (weak cash flow)"

        except Exception as e:
            logger.warning(f"Could not assess earnings quality: {e}")

        return quality

    # ==================== Comprehensive Analysis ====================

    def analyze(self) -> Dict[str, Any]:
        """
        Run comprehensive valuation analysis

        Returns:
            Dictionary with all valuation results
        """
        return {
            "ticker": self.ticker,
            "dcf_valuation": self.calculate_dcf_valuation(),
            "ddm_valuation": self.calculate_ddm_valuation(),
            "dividend_analysis": self.analyze_dividends(),
            "earnings_analysis": self.analyze_earnings(),
        }

    def format_markdown(self) -> List[str]:
        """
        Format valuation analysis as markdown report

        Returns:
            List of markdown lines
        """
        md = []
        md.append("\n## Valuation Analysis")
        md.append("")

        results = self.analyze()
        currency_symbols = {"USD": "$", "CAD": "CA$", "NOK": "kr", "EUR": "€", "GBP": "£"}
        symbol = currency_symbols.get(self.currency, self.currency)

        # DCF Valuation
        md.append("### DCF (Discounted Cash Flow) Valuation")
        md.append("")
        dcf = results["dcf_valuation"]

        if dcf.get("error"):
            md.append(f"*{dcf['error']}*")
            md.append("")
        elif dcf.get("intrinsic_value_per_share"):
            intrinsic = dcf["intrinsic_value_per_share"]
            current = dcf.get("current_price", 0)
            discount = dcf.get("discount_premium_pct", 0)

            md.append("| Metric | Value |")
            md.append("|--------|-------|")
            md.append(f"| Intrinsic Value per Share | {symbol}{intrinsic:,.2f} |")
            md.append(f"| Current Price | {symbol}{current:,.2f} |")
            if discount:
                direction = "Premium" if discount > 0 else "Discount"
                md.append(f"| {direction} | {abs(discount):.1f}% |")
            md.append("")

            md.append("**Assumptions:**")
            md.append("")
            if dcf.get("fcf_current"):
                md.append(f"- Current FCF: {symbol}{dcf['fcf_current']:,.0f}")
            if dcf.get("growth_rate_used"):
                md.append(f"- Growth Rate: {dcf['growth_rate_used']:.2f}%")
            if dcf.get("terminal_growth_rate"):
                md.append(f"- Terminal Growth: {dcf['terminal_growth_rate']:.2f}%")
            if dcf.get("wacc_used"):
                md.append(f"- WACC: {dcf['wacc_used']:.2f}%")
            md.append("")
        else:
            md.append("*Insufficient data for DCF valuation*")
            md.append("")

        # DDM Valuation
        md.append("### DDM (Dividend Discount Model) Valuation")
        md.append("")
        ddm = results["ddm_valuation"]

        if ddm.get("error"):
            md.append(f"*{ddm['error']}*")
            md.append("")
        elif ddm.get("intrinsic_value_per_share"):
            intrinsic = ddm["intrinsic_value_per_share"]
            current = ddm.get("current_price", 0)
            discount = ddm.get("discount_premium_pct", 0)

            md.append("| Metric | Value |")
            md.append("|--------|-------|")
            md.append(f"| Intrinsic Value per Share | {symbol}{intrinsic:,.2f} |")
            md.append(f"| Current Price | {symbol}{current:,.2f} |")
            if discount:
                direction = "Premium" if discount > 0 else "Discount"
                md.append(f"| {direction} | {abs(discount):.1f}% |")
            md.append("")

            md.append("**Assumptions:**")
            md.append("")
            if ddm.get("current_dividend"):
                md.append(f"- Current Annual Dividend: {symbol}{ddm['current_dividend']:.2f}")
            if ddm.get("growth_rate_used"):
                md.append(f"- Dividend Growth Rate: {ddm['growth_rate_used']:.2f}%")
            if ddm.get("required_return_used"):
                md.append(f"- Required Return: {ddm['required_return_used']:.2f}%")
            md.append("")
        else:
            md.append("*Insufficient data for DDM valuation*")
            md.append("")

        # Dividend Analysis
        md.append("### Dividend Analysis")
        md.append("")
        div = results["dividend_analysis"]

        if div.get("pays_dividends"):
            md.append("| Metric | Value |")
            md.append("|--------|-------|")

            if div.get("dividend_yield"):
                md.append(f"| Dividend Yield | {div['dividend_yield']:.2f}% |")
            if div.get("annual_dividend"):
                md.append(f"| Annual Dividend | {symbol}{div['annual_dividend']:.2f} |")
            if div.get("payout_ratio"):
                md.append(f"| Payout Ratio | {div['payout_ratio']:.1f}% |")
            if div.get("dividend_coverage_ratio"):
                md.append(f"| Coverage Ratio | {div['dividend_coverage_ratio']:.2f}x |")
            if div.get("dividend_growth_rate"):
                md.append(f"| Growth Rate (Historical) | {div['dividend_growth_rate']:.2f}% |")
            if div.get("consecutive_years"):
                md.append(f"| Consecutive Years Paid | {div['consecutive_years']} |")
            md.append("")

            # Sustainability
            if div.get("sustainability_score") is not None:
                score = div["sustainability_score"]
                rating = div.get("sustainability_rating", "N/A")
                md.append(f"**Sustainability:** {score}/100 ({rating})")
                md.append("")

                if div.get("warnings"):
                    md.append("**Warnings:**")
                    md.append("")
                    for warning in div["warnings"]:
                        md.append(f"- {warning}")
                    md.append("")
        else:
            md.append("*Company does not pay dividends*")
            md.append("")

        # Earnings Analysis
        md.append("### Earnings Analysis")
        md.append("")
        earnings = results["earnings_analysis"]

        if earnings.get("current_eps"):
            md.append("| Metric | Value |")
            md.append("|--------|-------|")
            md.append(f"| Current EPS (TTM) | {symbol}{earnings['current_eps']:.2f} |")
            if earnings.get("forward_eps"):
                md.append(f"| Forward EPS | {symbol}{earnings['forward_eps']:.2f} |")
            if earnings.get("eps_growth_1y"):
                md.append(f"| EPS Growth (1Y) | {earnings['eps_growth_1y']:+.1f}% |")
            if earnings.get("eps_growth_3y_cagr"):
                md.append(f"| EPS Growth (3Y CAGR) | {earnings['eps_growth_3y_cagr']:+.1f}% |")
            md.append("")

            # Trend
            if earnings.get("trend"):
                md.append(f"**Trend:** {earnings['trend']}")
                md.append("")

            # Earnings quality
            quality = earnings.get("earnings_quality", {})
            if quality.get("assessment"):
                md.append(f"**Earnings Quality:** {quality['assessment']}")
                if quality.get("score"):
                    md.append(f"*(OCF/NI Ratio: {quality['score']:.2f})*")
                md.append("")

            # Recent surprises
            surprises = earnings.get("recent_surprises", [])
            if surprises:
                md.append("**Recent Earnings Surprises:**")
                md.append("")
                md.append("| Quarter | Actual | Estimate | Surprise % |")
                md.append("|---------|--------|----------|------------|")
                for surprise in surprises[:4]:  # Last 4 quarters
                    quarter = surprise.get("quarter", "N/A")
                    actual = surprise.get("actual", 0)
                    estimate = surprise.get("estimate", 0)
                    surprise_pct = surprise.get("surprise_pct", 0)
                    surprise_dir = "+" if surprise_pct >= 0 else ""
                    md.append(
                        f"| {quarter} | {symbol}{actual:.2f} | {symbol}{estimate:.2f} | "
                        f"{surprise_dir}{surprise_pct * 100:.1f}% |"
                    )
                md.append("")
        else:
            md.append("*Earnings data unavailable*")
            md.append("")

        return md
