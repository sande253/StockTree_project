"""Compute correlations for all companies vs STLA (Phase 5)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import logging
import pandas as pd
from scipy import stats

from storage.duckdb import get_connection

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def compute_correlations(reference_ticker: str = 'STLA'):
    """Compute Pearson correlations for all tickers vs reference ticker."""
    logger.info(f"Computing correlations vs {reference_ticker}...")
    
    conn = get_connection()
    
    # Get reference ticker returns
    ref_df = conn.execute("""
        WITH returns AS (
            SELECT 
                date,
                adj_close,
                LAG(adj_close) OVER (ORDER BY date) as prev_close
            FROM price_data
            WHERE ticker = ?
            ORDER BY date
        )
        SELECT 
            date,
            (adj_close / prev_close - 1) as return
        FROM returns
        WHERE prev_close IS NOT NULL
    """, [reference_ticker]).df()
    
    if ref_df.empty:
        logger.error(f"No data for reference ticker {reference_ticker}")
        return
    
    # Get all unique tickers
    tickers = conn.execute("""
        SELECT DISTINCT ticker 
        FROM price_data 
        WHERE ticker != ?
    """, [reference_ticker]).fetchall()
    
    results = []
    
    for (ticker,) in tickers:
        try:
            # Get ticker returns
            ticker_df = conn.execute("""
                WITH returns AS (
                    SELECT 
                        date,
                        adj_close,
                        LAG(adj_close) OVER (ORDER BY date) as prev_close
                    FROM price_data
                    WHERE ticker = ?
                    ORDER BY date
                )
                SELECT 
                    date,
                    (adj_close / prev_close - 1) as return
                FROM returns
                WHERE prev_close IS NOT NULL
            """, [ticker]).df()
            
            # Merge on date
            merged = pd.merge(ref_df, ticker_df, on='date', suffixes=('_ref', '_ticker'))
            
            if len(merged) < 30:
                logger.warning(f"{ticker}: Insufficient data ({len(merged)} points)")
                continue
            
            # Calculate correlation
            corr, p_value = stats.pearsonr(merged['return_ref'], merged['return_ticker'])
            
            results.append({
                'ticker': ticker,
                'reference_ticker': reference_ticker,
                'pearson_correlation': float(corr),
                'pearson_p_value': float(p_value),
                'sample_size': len(merged)
            })
            
            logger.info(f"  {ticker}: r={corr:.3f}, p={p_value:.4f}, n={len(merged)}")
        
        except Exception as e:
            logger.error(f"  {ticker}: Error - {e}")
    
    # Insert into database
    if results:
        results_df = pd.DataFrame(results)
        conn.register('correlations_temp', results_df)

        conn.execute("""
            INSERT INTO correlations (ticker, reference_ticker, pearson_correlation, pearson_p_value, sample_size)
            SELECT ticker, reference_ticker, pearson_correlation, pearson_p_value, sample_size
            FROM correlations_temp
            ON CONFLICT (ticker, reference_ticker) DO UPDATE SET
                pearson_correlation = excluded.pearson_correlation,
                pearson_p_value = excluded.pearson_p_value,
                sample_size = excluded.sample_size,
                computed_at = now()
        """)
        conn.unregister('correlations_temp')

        logger.info(f"\n✓ Computed {len(results)} correlations")
    
    conn.close()


if __name__ == '__main__':
    compute_correlations()
