"""Unit tests for the anomaly analyzer."""

import pytest
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from anomaly_detector.analyzer import AnomalyAnalyzer, AnomalyType, AnomalyResult


class TestZScoreCalculation:
    """Tests for Z-score calculation."""
    
    def test_zscore_normal_distribution(self):
        """Z-score should be 0 when price equals mean."""
        analyzer = AnomalyAnalyzer()
        history = [100.0, 100.0, 100.0, 100.0, 100.0]
        # With zero variance, should return 0
        zscore = analyzer.calculate_zscore(100.0, history)
        assert zscore == 0.0
    
    def test_zscore_below_mean(self):
        """Z-score should be negative when price is below mean."""
        analyzer = AnomalyAnalyzer()
        # Mean = 100, stdev ≈ 10
        history = [90.0, 95.0, 100.0, 105.0, 110.0]
        zscore = analyzer.calculate_zscore(70.0, history)
        # Price 70 should be significantly below mean of 100
        assert zscore < -2
    
    def test_zscore_above_mean(self):
        """Z-score should be positive when price is above mean."""
        analyzer = AnomalyAnalyzer()
        history = [90.0, 95.0, 100.0, 105.0, 110.0]
        zscore = analyzer.calculate_zscore(130.0, history)
        assert zscore > 2
    
    def test_zscore_insufficient_data(self):
        """Z-score should be 0 with insufficient data."""
        analyzer = AnomalyAnalyzer()
        history = [100.0]  # Only 1 point
        zscore = analyzer.calculate_zscore(50.0, history)
        assert zscore == 0.0
    
    def test_zscore_empty_history(self):
        """Z-score should handle empty history."""
        analyzer = AnomalyAnalyzer()
        zscore = analyzer.calculate_zscore(50.0, [])
        assert zscore == 0.0


class TestDropDetection:
    """Tests for sudden drop percentage calculation."""
    
    def test_drop_from_higher_price(self):
        """Should detect drop correctly."""
        analyzer = AnomalyAnalyzer()
        recent = [100.0, 100.0, 100.0]
        drop = analyzer.calculate_drop_percent(30.0, recent)
        assert drop == 70.0  # 70% drop
    
    def test_no_drop(self):
        """Should return 0 or negative when no drop."""
        analyzer = AnomalyAnalyzer()
        recent = [100.0, 100.0, 100.0]
        drop = analyzer.calculate_drop_percent(100.0, recent)
        assert drop == 0.0
    
    def test_price_increase(self):
        """Should return negative when price increased."""
        analyzer = AnomalyAnalyzer()
        recent = [100.0, 100.0, 100.0]
        drop = analyzer.calculate_drop_percent(150.0, recent)
        assert drop < 0  # Price went up
    
    def test_empty_history(self):
        """Should handle empty history."""
        analyzer = AnomalyAnalyzer()
        drop = analyzer.calculate_drop_percent(50.0, [])
        assert drop == 0.0


class TestAnomalyAnalysis:
    """Integration tests for full anomaly analysis."""
    
    def test_no_anomaly_normal_price(self):
        """Normal price should not trigger anomaly."""
        analyzer = AnomalyAnalyzer()
        history = [100.0] * 10  # 10 stable prices
        result = analyzer.analyze(95.0, history)  # 5% drop
        assert not result.is_anomaly
        assert result.anomaly_type is None
    
    def test_zscore_anomaly(self):
        """Should detect Z-score anomaly."""
        analyzer = AnomalyAnalyzer()
        # Stable prices around 100, then a big drop
        history = [100.0, 102.0, 98.0, 101.0, 99.0, 100.0]
        result = analyzer.analyze(50.0, history)  # 50% off normal
        assert result.is_anomaly
        assert result.anomaly_type in [AnomalyType.ZSCORE, AnomalyType.BOTH]
        assert result.zscore < -3
    
    def test_sudden_drop_anomaly(self):
        """Should detect sudden drop anomaly."""
        analyzer = AnomalyAnalyzer()
        # Recent prices were high, now crashed
        history = [200.0, 200.0, 200.0]
        result = analyzer.analyze(50.0, history)  # 75% drop
        assert result.is_anomaly
        assert result.drop_percent > 70
    
    def test_both_anomalies(self):
        """Should detect when both conditions are met."""
        analyzer = AnomalyAnalyzer()
        # Long stable history, then huge drop
        history = [100.0] * 10
        result = analyzer.analyze(10.0, history)  # 90% drop
        # Note: with zero variance, Z-score is 0, so only drop detected
        # Need some variance for both
        history_varied = [95.0, 100.0, 105.0, 98.0, 102.0, 100.0]
        result = analyzer.analyze(20.0, history_varied)
        assert result.is_anomaly
        assert result.drop_percent > 70
    
    def test_insufficient_history_no_anomaly(self):
        """Should not flag anomaly with insufficient history."""
        analyzer = AnomalyAnalyzer()
        history = [100.0, 100.0]  # Only 2 points
        result = analyzer.analyze(10.0, history)  # 90% drop
        # But we don't have enough history to be sure
        # MIN_HISTORY_FOR_DROP = 3, MIN_HISTORY_FOR_ZSCORE = 5
        assert not result.is_anomaly


class TestAnomalyResult:
    """Tests for AnomalyResult properties."""
    
    def test_severity_critical(self):
        """Both anomalies should be CRITICAL."""
        result = AnomalyResult(
            is_anomaly=True,
            anomaly_type=AnomalyType.BOTH,
            current_price=10.0,
            mean_price=100.0,
            zscore=-5.0,
            drop_percent=90.0,
            recent_avg=100.0,
            history_count=10,
        )
        assert result.severity == "CRITICAL"
    
    def test_severity_high(self):
        """Extreme Z-score should be HIGH."""
        result = AnomalyResult(
            is_anomaly=True,
            anomaly_type=AnomalyType.ZSCORE,
            current_price=10.0,
            mean_price=100.0,
            zscore=-4.5,
            drop_percent=20.0,
            recent_avg=100.0,
            history_count=10,
        )
        assert result.severity == "HIGH"
    
    def test_severity_moderate(self):
        """Regular anomaly should be MODERATE."""
        result = AnomalyResult(
            is_anomaly=True,
            anomaly_type=AnomalyType.ZSCORE,
            current_price=60.0,
            mean_price=100.0,
            zscore=-3.5,
            drop_percent=40.0,
            recent_avg=100.0,
            history_count=10,
        )
        assert result.severity == "MODERATE"
    
    def test_severity_none(self):
        """Non-anomaly should be NONE."""
        result = AnomalyResult(
            is_anomaly=False,
            anomaly_type=None,
            current_price=95.0,
            mean_price=100.0,
            zscore=-0.5,
            drop_percent=5.0,
            recent_avg=100.0,
            history_count=10,
        )
        assert result.severity == "NONE"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
