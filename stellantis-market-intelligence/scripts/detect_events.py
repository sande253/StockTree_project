"""Batch event detection script.

Run after market data ingestion to detect significant STLA movements.
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime, timedelta

from events.detector import EventDetector
from storage.duckdb import get_connection

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def detect_events(ticker: str = 'STLA', days: int = 90):
    """Detect events for a ticker over a period.
    
    Args:
        ticker: Stock ticker to analyze
        days: Number of days to look back
    """
    logger.info(f"Starting event detection for {ticker}")
    logger.info(f"Period: Last {days} days")
    
    detector = EventDetector()
    
    try:
        events = detector.detect_events(ticker, days=days)
        
        if not events:
            logger.info("No significant events detected")
            return
        
        logger.info(f"Detected {len(events)} events")
        
        # Display event summary
        for event in events:
            logger.info(
                f"Event {event['event_date']}: "
                f"{event['return']*100:.2f}% "
                f"(severity: {event.get('severity', 'N/A')})"
            )
        
        # Store events in database
        conn = get_connection()
        conn.execute("CREATE TABLE IF NOT EXISTS events AS SELECT * FROM events WHERE 1=0")
        
        # Count events in database
        result = conn.execute("SELECT COUNT(*) FROM events WHERE ticker = ?", [ticker]).fetchone()
        logger.info(f"Total events in database for {ticker}: {result[0]}")
        
    except Exception as e:
        logger.error(f"Event detection failed: {e}")
        raise


def main():
    parser = argparse.ArgumentParser(
        description='Detect significant market events'
    )
    parser.add_argument(
        '--ticker',
        default='STLA',
        help='Ticker to analyze (default: STLA)'
    )
    parser.add_argument(
        '--days',
        type=int,
        default=90,
        help='Number of days to analyze (default: 90)'
    )
    parser.add_argument(
        '--threshold',
        type=float,
        help='Custom return threshold (e.g., 0.05 for 5%%)'
    )
    
    args = parser.parse_args()
    
    detect_events(ticker=args.ticker, days=args.days)


if __name__ == '__main__':
    main()
