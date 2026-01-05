"""Statistical anomaly detection for price data."""

import statistics
import logging
from enum import Enum
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


class AnomalyType(Enum):
    """Types of price anomalies detected."""
    ZSCORE = "zscore"           # Price is >3σ below historical mean
    SUDDEN_DROP = "sudden_drop"  # >70% drop vs recent prices
    BOTH = "both"               # Both conditions met


@dataclass
class AnomalyResult:
    """Result of anomaly analysis for a single item."""
    is_anomaly: bool
    anomaly_type: Optional[AnomalyType]
    current_price: float
    mean_price: float
    zscore: float
    drop_percent: float
    recent_avg: float
    history_count: int
    
    @property
    def severity(self) -> str:
        """Return severity level based on anomaly metrics."""
        if self.anomaly_type == AnomalyType.BOTH:
            return "CRITICAL"
        elif self.zscore < -4 or self.drop_percent > 80:
            return "HIGH"
        elif self.is_anomaly:
            return "MODERATE"
        return "NONE"


class AnomalyAnalyzer:
    """
    Statistical analyzer for detecting price anomalies.
    
    Uses two detection methods:
    1. Z-Score: Flags if current price is >3 standard deviations below mean
    2. Sudden Drop: Flags if current price is >70% below recent average (last 3 points)
    """
    
    # Thresholds (configurable)
    ZSCORE_THRESHOLD = -3.0      # Flag if Z < -3
    DROP_THRESHOLD = 70.0        # Flag if drop > 70%
    MIN_HISTORY_FOR_ZSCORE = 5   # Need at least 5 data points for meaningful Z-score
    MIN_HISTORY_FOR_DROP = 3     # Need at least 3 data points for drop detection
    
    def __init__(
        self,
        zscore_threshold: float = ZSCORE_THRESHOLD,
        drop_threshold: float = DROP_THRESHOLD,
    ):
        self.zscore_threshold = zscore_threshold
        self.drop_threshold = drop_threshold
    
    @staticmethod
    def calculate_zscore(current_price: float, history: list[float]) -> float:
        """
        Calculate Z-score for current price against historical prices.
        
        Z = (x - μ) / σ
        
        A negative Z-score means price is below the mean.
        Z < -3 means price is more than 3 standard deviations below mean.
        
        Returns 0 if insufficient data or zero variance.
        """
        if len(history) < 2:
            return 0.0
        
        try:
            mean = statistics.mean(history)
            stdev = statistics.stdev(history)
            
            if stdev == 0:
                # No variance in history - can't calculate meaningful Z-score
                return 0.0
            
            return (current_price - mean) / stdev
            
        except statistics.StatisticsError:
            return 0.0
    
    @staticmethod
    def calculate_drop_percent(current_price: float, recent_prices: list[float]) -> float:
        """
        Calculate percentage drop from recent average.
        
        Compares current price to average of last N prices.
        Returns positive value if price dropped (e.g., 70 = 70% drop).
        Returns 0 or negative if price increased.
        """
        if not recent_prices:
            return 0.0
        
        avg_recent = statistics.mean(recent_prices)
        
        if avg_recent == 0:
            return 0.0
        
        drop_pct = (avg_recent - current_price) / avg_recent * 100
        return drop_pct
    
    def analyze(self, current_price: float, price_history: list[float]) -> AnomalyResult:
        """
        Analyze current price against historical data.
        
        Args:
            current_price: The newly scraped price
            price_history: Historical prices (oldest first)
        
        Returns:
            AnomalyResult with detection details
        """
        # Calculate statistics
        mean_price = statistics.mean(price_history) if price_history else current_price
        zscore = self.calculate_zscore(current_price, price_history)
        
        # Get recent prices (last 3) for sudden drop detection
        recent_prices = price_history[-3:] if len(price_history) >= 3 else price_history
        recent_avg = statistics.mean(recent_prices) if recent_prices else current_price
        drop_percent = self.calculate_drop_percent(current_price, recent_prices)
        
        # Detect anomalies
        is_zscore_anomaly = (
            len(price_history) >= self.MIN_HISTORY_FOR_ZSCORE and 
            zscore < self.zscore_threshold
        )
        is_drop_anomaly = (
            len(price_history) >= self.MIN_HISTORY_FOR_DROP and 
            drop_percent > self.drop_threshold
        )
        
        # Determine anomaly type
        if is_zscore_anomaly and is_drop_anomaly:
            anomaly_type = AnomalyType.BOTH
        elif is_zscore_anomaly:
            anomaly_type = AnomalyType.ZSCORE
        elif is_drop_anomaly:
            anomaly_type = AnomalyType.SUDDEN_DROP
        else:
            anomaly_type = None
        
        is_anomaly = anomaly_type is not None
        
        if is_anomaly:
            logger.info(
                f"Anomaly detected: Z={zscore:.2f}, Drop={drop_percent:.1f}%, "
                f"Type={anomaly_type.value if anomaly_type else 'none'}"
            )
        
        return AnomalyResult(
            is_anomaly=is_anomaly,
            anomaly_type=anomaly_type,
            current_price=current_price,
            mean_price=mean_price,
            zscore=zscore,
            drop_percent=drop_percent,
            recent_avg=recent_avg,
            history_count=len(price_history),
        )
    
    def should_alert(self, result: AnomalyResult) -> bool:
        """
        Determine if an anomaly result warrants a Discord alert.
        
        Currently alerts on any detected anomaly.
        Could be extended to filter by severity, time since last alert, etc.
        """
        return result.is_anomaly
