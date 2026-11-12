"""Batch market data ingestion script.

Run daily/hourly to fetch and update market data for all companies.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
import logging
from dataclasses import asdict
from datetime import datetime, timedelta

from ingestion.market_data import ingest_price_history
from storage.duckdb import get_connection
from storage.load_companies import load_companies_config

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def load_companies() -> list[dict]:
    """Load company list from config."""
    return [asdict(company) for company in load_companies_config()]


def ingest_all_companies(days: int = 90, interval: str = '1d'):
    """Ingest market data for all configured companies.
    
    Args:
        days: Number of days of historical data to fetch
        interval: Data interval (1d, 1h, etc.)
    """
    if days <= 0:
        raise ValueError("days must be positive")
    companies = load_companies()

    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    
    logger.info(f"Starting market data ingestion for {len(companies)} companies")
    logger.info(f"Period: {start_date.date()} to {end_date.date()}")
    logger.info(f"Interval: {interval}")
    
    success_count = 0
    error_count = 0
    
    for company in companies:
        ticker = company.get('ticker')
        if not ticker:
            logger.warning(f"Skipping company without ticker: {company.get('name')}")
            continue
        
        try:
            logger.info(f"Ingesting {ticker}...")
            ingest_price_history(
                ticker=ticker,
                start=start_date.strftime('%Y-%m-%d'),
                end=end_date.strftime('%Y-%m-%d'),
                interval=interval,
            )
            success_count += 1
            logger.info(f"✓ {ticker} completed")
        except Exception as e:
            error_count += 1
            logger.error(f"✗ {ticker} failed: {e}")
    
    logger.info(f"Ingestion complete: {success_count} succeeded, {error_count} failed")
    
    # Verify data in database
    conn = get_connection()
    try:
        result = conn.execute("SELECT COUNT(DISTINCT ticker) FROM price_data").fetchone()
        logger.info(f"Database contains data for {result[0]} tickers")
    except Exception as e:
        logger.warning(f"Could not verify database: {e}")
        error_count += 1
    finally:
        conn.close()
    return {"succeeded": success_count, "failed": error_count}


def main():
    parser = argparse.ArgumentParser(
        description='Ingest market data for all configured companies'
    )
    parser.add_argument(
        '--days',
        type=int,
        default=90,
        help='Number of days of historical data to fetch (default: 90)'
    )
    parser.add_argument(
        '--interval',
        default='1d',
        choices=['1d', '1h', '1wk', '1mo'],
        help='Data interval (default: 1d)'
    )
    parser.add_argument(
        '--ticker',
        help='Ingest data for a single ticker only'
    )
    
    args = parser.parse_args()
    if args.days <= 0:
        parser.error("--days must be positive")
    
    if args.ticker:
        # Single ticker mode
        logger.info(f"Single ticker mode: {args.ticker}")
        end_date = datetime.now()
        start_date = end_date - timedelta(days=args.days)
        
        ingest_price_history(
            ticker=args.ticker,
            start=start_date.strftime('%Y-%m-%d'),
            end=end_date.strftime('%Y-%m-%d'),
            interval=args.interval
        )
        logger.info(f"✓ {args.ticker} completed")
    else:
        # All companies mode
        result = ingest_all_companies(days=args.days, interval=args.interval)
        if result["failed"]:
            raise SystemExit(1)


if __name__ == '__main__':
    main()
