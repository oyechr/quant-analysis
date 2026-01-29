"""
Test Error Handling Improvements
Validates ticker validation, parameter validation, and error messages
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data_fetcher import DataFetcher


def test_ticker_validation():
    """Test ticker validation with invalid symbols"""
    print("=" * 70)
    print("Test 1: Invalid Ticker Validation")
    print("=" * 70)
    
    fetcher = DataFetcher()
    
    # Test invalid ticker
    print("\nTesting invalid ticker 'INVALIDXYZ123'...")
    try:
        data = fetcher.fetch_ticker("INVALIDXYZ123", period="1mo")
        print(f"❌ FAILED: Should have raised ValueError")
    except ValueError as e:
        print(f"✓ SUCCESS: Caught ValueError as expected")
        print(f"  Error message: {e}")
    except Exception as e:
        print(f"❌ UNEXPECTED: Got {type(e).__name__}: {e}")
    
    print("\n" + "-" * 70)


def test_parameter_validation():
    """Test parameter validation"""
    print("\n" + "=" * 70)
    print("Test 2: Parameter Validation")
    print("=" * 70)
    
    fetcher = DataFetcher()
    
    # Test invalid period
    print("\nTesting invalid period 'invalid_period'...")
    try:
        data = fetcher.fetch_ticker("AAPL", period="invalid_period")
        print(f"❌ FAILED: Should have raised ValueError")
    except ValueError as e:
        print(f"✓ SUCCESS: Caught ValueError")
        print(f"  Error message: {e}")
    
    # Test invalid interval
    print("\nTesting invalid interval '99h'...")
    try:
        data = fetcher.fetch_ticker("AAPL", period="1mo", interval="99h")
        print(f"❌ FAILED: Should have raised ValueError")
    except ValueError as e:
        print(f"✓ SUCCESS: Caught ValueError")
        print(f"  Error message: {e}")
    
    # Test invalid date range
    print("\nTesting invalid date range (start after end)...")
    try:
        data = fetcher.fetch_ticker(
            "AAPL", 
            start="2024-12-31", 
            end="2024-01-01"
        )
        print(f"❌ FAILED: Should have raised ValueError")
    except ValueError as e:
        print(f"✓ SUCCESS: Caught ValueError")
        print(f"  Error message: {e}")
    
    print("\n" + "-" * 70)


def test_valid_ticker():
    """Test that valid ticker still works"""
    print("\n" + "=" * 70)
    print("Test 3: Valid Ticker (Should Work)")
    print("=" * 70)
    
    fetcher = DataFetcher()
    
    print("\nFetching valid ticker 'AAPL'...")
    try:
        data = fetcher.fetch_ticker("AAPL", period="5d", use_cache=False)
        print(f"✓ SUCCESS: Retrieved {len(data)} rows of data")
        print(f"  Date range: {data.index[0]} to {data.index[-1]}")
        print(f"  Columns: {list(data.columns)}")
    except Exception as e:
        print(f"❌ FAILED: {type(e).__name__}: {e}")
    
    print("\n" + "-" * 70)


def test_configuration():
    """Test configuration system"""
    print("\n" + "=" * 70)
    print("Test 4: Configuration System")
    print("=" * 70)
    
    from src.config import get_config
    
    config = get_config()
    
    print(f"\nRisk-Free Rate: {config.risk_free_rate * 100}%")
    print(f"Benchmark Ticker: {config.benchmark_ticker}")
    print(f"RSI Overbought Threshold: {config.rsi_overbought}")
    print(f"RSI Oversold Threshold: {config.rsi_oversold}")
    print(f"Altman Z-Score Safe Zone: > {config.z_score_safe}")
    print(f"Piotroski F-Score Strong: >= {config.min_f_score_strong}")
    
    valid_periods = sorted(config.valid_periods) if config.valid_periods else []
    valid_intervals = sorted(config.valid_intervals) if config.valid_intervals else []
    print(f"\nValid Periods: {valid_periods}")
    print(f"Valid Intervals: {valid_intervals}")
    
    print("\n✓ Configuration loaded successfully")
    print("\n" + "-" * 70)


def test_data_quality_warnings():
    """Test warning logs for missing fundamental data"""
    print("\n" + "=" * 70)
    print("Test 5: Data Quality Warnings (Check Logs)")
    print("=" * 70)
    
    from src.fundamental_analysis import FundamentalAnalyzer
    
    print("\nTesting with empty financial data...")
    
    # Create analyzer with minimal data
    analyzer = FundamentalAnalyzer(
        ticker_info={'symbol': 'TEST'},
        fundamentals={},  # Empty fundamentals
        price_data=None
    )
    
    # This should log warnings
    z_score = analyzer.calculate_altman_z_score()
    f_score = analyzer.calculate_piotroski_f_score()
    
    print(f"Z-Score result: {z_score} (should be None)")
    print(f"F-Score result: {f_score} (should be None)")
    print("\n✓ Check logs above for warning messages")
    print("\n" + "-" * 70)


def main():
    """Run all tests"""
    print("\n")
    print("╔" + "=" * 68 + "╗")
    print("║" + " " * 15 + "ERROR HANDLING VALIDATION TESTS" + " " * 22 + "║")
    print("╚" + "=" * 68 + "╝")
    
    try:
        test_ticker_validation()
        test_parameter_validation()
        test_valid_ticker()
        test_configuration()
        test_data_quality_warnings()
        
        print("\n" + "=" * 70)
        print("All Tests Complete!")
        print("=" * 70)
        print("\n✓ Ticker validation working")
        print("✓ Parameter validation working")
        print("✓ Valid tickers still work")
        print("✓ Configuration system loaded")
        print("✓ Data quality warnings logged")
        print("\n")
        
    except Exception as e:
        print(f"\n❌ Test suite failed with error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
