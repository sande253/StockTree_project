"""Fetch market data for the configured company universe and compare returns.

This script:
1. Fetches latest STLA data from Yahoo Finance
2. Detects actual STLA market events
3. Fetches data for companies in the market-data universe
4. Reports observed market co-movement without inferring business relationships
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd

from ingestion.market_data import ingest_price_history, MarketDataError
from storage.duckdb import get_connection

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def _market_universe() -> dict[str, str]:
    from storage.repository import list_companies

    return {company["ticker"]: company["company_name"] for company in list_companies()}


def fetch_live_data(ticker: str, days: int = 180) -> pd.DataFrame | None:
    """Fetch live market data from Yahoo Finance."""
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    
    try:
        logger.info(f"Fetching {ticker}...")
        summary = ingest_price_history(
            ticker=ticker,
            start=start_date.strftime('%Y-%m-%d'),
            end=end_date.strftime('%Y-%m-%d'),
            interval='1d'
        )
        logger.info(f"✓ {ticker}: {summary['rows_ingested']} rows")
        
        # Retrieve the data
        conn = get_connection()
        df = conn.execute(
            "SELECT * FROM price_data WHERE ticker = ? ORDER BY date DESC LIMIT 180",
            [ticker]
        ).df()
        conn.close()
        
        return df if not df.empty else None
        
    except MarketDataError as e:
        logger.warning(f"✗ {ticker}: {e}")
        return None
    except Exception as e:
        logger.error(f"✗ {ticker}: Unexpected error: {e}")
        return None


def detect_recent_stla_events() -> list[dict]:
    """Detect significant STLA events in recent data."""
    logger.info("Detecting recent STLA events...")
    
    conn = get_connection()
    df = conn.execute("""
        SELECT date, close, adj_close, volume
        FROM price_data
        WHERE ticker = 'STLA'
        ORDER BY date DESC
        LIMIT 90
    """).df()
    conn.close()
    
    if df.empty:
        logger.warning("No STLA data available for event detection")
        return []
    
    # Calculate returns
    df = df.sort_values('date')
    df['return'] = df['adj_close'].pct_change()
    df['volume_change'] = df['volume'].pct_change()
    
    # Detect significant events (>4% move or unusual volume)
    events = []
    for idx, row in df.iterrows():
        if pd.isna(row['return']):
            continue
            
        if abs(row['return']) > 0.04 or abs(row['volume_change']) > 2.0:
            events.append({
                'date': row['date'],
                'return': row['return'],
                'price': row['adj_close'],
                'volume': row['volume'],
                'volume_change': row['volume_change'],
                'severity': 'High' if abs(row['return']) > 0.06 else 'Medium'
            })
    
    logger.info(f"Detected {len(events)} significant events")
    return events


def analyze_correlations() -> dict:
    """Analyze correlations between STLA and ecosystem companies."""
    logger.info("Analyzing correlations with ecosystem companies...")
    
    conn = get_connection()
    
    # Get STLA returns
    stla_df = conn.execute("""
        SELECT date, adj_close as stla_price
        FROM price_data
        WHERE ticker = 'STLA'
        ORDER BY date
    """).df()
    
    if stla_df.empty:
        logger.warning("No STLA data for correlation analysis")
        return {}
    
    stla_df['stla_return'] = stla_df['stla_price'].pct_change()
    
    correlations = {}
    
    for ticker, company_name in _market_universe().items():
        if ticker == 'STLA':
            continue
            
        try:
            company_df = conn.execute("""
                SELECT date, adj_close as price
                FROM price_data
                WHERE ticker = ?
                ORDER BY date
            """, [ticker]).df()
            
            if company_df.empty:
                continue
            
            company_df['return'] = company_df['price'].pct_change()
            
            # Merge on date
            merged = pd.merge(stla_df, company_df, on='date', how='inner')
            
            if len(merged) < 30:  # Need sufficient data
                continue
            
            # Calculate correlation
            corr = merged['stla_return'].corr(merged['return'])
            
            if pd.notna(corr):
                correlations[ticker] = {
                    'name': company_name,
                    'correlation': round(float(corr), 3),
                    'data_points': len(merged)
                }
                
                logger.info(f"  {ticker}: correlation = {corr:.3f}")
        
        except Exception as e:
            logger.warning(f"  {ticker}: Error calculating correlation: {e}")
    
    conn.close()
    return correlations


def compare_same_day_moves(event_date: str) -> list[dict]:
    """Compare observed company returns on the same date as an STLA event."""
    logger.info(f"Comparing market returns on {event_date}...")
    
    conn = get_connection()
    
    # Get STLA return on event date (use LAG function instead of DATE_SUB)
    stla_return = conn.execute("""
        WITH returns AS (
            SELECT 
                date,
                adj_close,
                LAG(adj_close) OVER (ORDER BY date) as prev_close
            FROM price_data
            WHERE ticker = 'STLA'
        )
        SELECT (adj_close / prev_close - 1) as return
        FROM returns
        WHERE date = ?
    """, [event_date]).fetchone()
    
    if not stla_return or stla_return[0] is None:
        return []
    
    stla_return_val = stla_return[0]
    
    affected = []
    
    for ticker, company_name in _market_universe().items():
        if ticker == 'STLA':
            continue
        
        try:
            company_return = conn.execute("""
                WITH returns AS (
                    SELECT 
                        date,
                        adj_close,
                        LAG(adj_close) OVER (ORDER BY date) as prev_close
                    FROM price_data
                    WHERE ticker = ?
                )
                SELECT (adj_close / prev_close - 1) as return
                FROM returns
                WHERE date = ?
            """, [ticker, event_date]).fetchone()
            
            if company_return and company_return[0]:
                return_val = company_return[0]
                
                # Check if moving in same direction as STLA
                same_direction = (stla_return_val * return_val) > 0
                magnitude = abs(return_val)
                
                if magnitude > 0.02:  # At least 2% move
                    affected.append({
                        'ticker': ticker,
                        'name': company_name,
                        'return': round(return_val, 4),
                        'same_direction': same_direction,
                        'magnitude': magnitude
                    })
        
        except Exception as e:
            pass
    
    conn.close()
    
    # Sort by magnitude
    affected.sort(key=lambda x: x['magnitude'], reverse=True)
    
    logger.info(f"Found {len(affected)} companies with notable same-day returns")
    return affected


def main():
    """Main execution flow."""
    logger.info("=" * 80)
    logger.info("STELLANTIS ECOSYSTEM LIVE DATA FETCH")
    logger.info("=" * 80)
    
    # 1. Fetch data for all ecosystem companies
    logger.info("\n1. Fetching live market data...")
    successful = 0
    failed = 0
    
    for ticker in _market_universe():
        df = fetch_live_data(ticker, days=180)
        if df is not None and not df.empty:
            successful += 1
        else:
            failed += 1
    
    logger.info(f"\nData fetch complete: {successful} successful, {failed} failed")
    
    # 2. Detect STLA events
    logger.info("\n2. Detecting STLA market events...")
    events = detect_recent_stla_events()
    
    if events:
        logger.info("\nRecent significant STLA events:")
        for event in events[:5]:  # Show top 5
            direction = "📉" if event['return'] < 0 else "📈"
            logger.info(
                f"  {event['date']} {direction} {event['return']*100:+.2f}% "
                f"(severity: {event['severity']}, volume: {event['volume_change']:+.1f}%)"
            )
    
    # 3. Analyze correlations
    logger.info("\n3. Analyzing market correlations...")
    correlations = analyze_correlations()
    
    if correlations:
        logger.info("\nLargest observed return correlations (not business relationships):")
        sorted_companies = sorted(correlations.items(), key=lambda item: abs(item[1]['correlation']), reverse=True)
        for ticker, data in sorted_companies[:10]:
            logger.info(f"  {ticker} ({data['name']}): {data['correlation']:+.3f}, n={data['data_points']}")
    
    # 4. Analyze recent event impacts
    if events:
        logger.info("\n4. Comparing same-day returns around the most recent event...")
        latest_event = events[0]
        affected = compare_same_day_moves(str(latest_event['date'].date()))
        
        if affected:
            logger.info(f"\nLargest same-day moves on {latest_event['date'].date()}:")
            for company in affected[:10]:
                direction = "📉" if company['return'] < 0 else "📈"
                sync = "✓" if company['same_direction'] else "✗"
                logger.info(
                    f"  {sync} {company['ticker']} ({company['name']}): "
                    f"{direction} {company['return']*100:+.2f}%"
                )
    
    logger.info("\n" + "=" * 80)
    logger.info("✓ LIVE ECOSYSTEM DATA FETCH COMPLETE")
    logger.info("=" * 80)
    logger.info("\nNext steps:")
    logger.info("  1. View ecosystem graph: http://localhost:8000/graph")
    logger.info("  2. View events: http://localhost:8000/events")
    logger.info("  3. View system status: http://localhost:8000/status")


if __name__ == '__main__':
    main()
