"""Complete all remaining analytical phases."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import logging
import subprocess

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def run_script(script_name: str):
    """Run a Python script and log output."""
    logger.info(f"\n{'='*80}")
    logger.info(f"Running: {script_name}")
    logger.info('='*80)
    
    try:
        result = subprocess.run(
            ['uv', 'run', 'python', f'scripts/{script_name}'],
            capture_output=True,
            text=True,
            timeout=300
        )
        
        if result.stdout:
            print(result.stdout)
        
        if result.returncode == 0:
            logger.info(f"✓ {script_name} completed successfully")
        else:
            logger.error(f"✗ {script_name} failed")
            if result.stderr:
                print(result.stderr)
        
        return result.returncode == 0
    
    except subprocess.TimeoutExpired:
        logger.error(f"✗ {script_name} timed out")
        return False
    except Exception as e:
        logger.error(f"✗ {script_name} error: {e}")
        return False


def main():
    logger.info("=== COMPLETING ALL ANALYTICAL PHASES ===\n")
    
    scripts = [
        ('compute_universe_correlations.py', 'Phase 5: Correlation Analysis'),
        ('run_event_studies.py', 'Phase 6: Event Study'),
        ('enrich_events.py', 'Phase 7/9/10: Event Market Context, Classification, News Correlation'),
        ('update_graph_from_live_data.py', 'Update: Refresh Graph'),
    ]
    
    results = {}
    
    for script, description in scripts:
        logger.info(f"\n{description}")
        success = run_script(script)
        results[description] = success
    
    # Summary
    logger.info("\n" + "="*80)
    logger.info("ANALYSIS COMPLETE - SUMMARY")
    logger.info("="*80)
    
    for description, success in results.items():
        status = "✓" if success else "✗"
        logger.info(f"  {status} {description}")
    
    success_count = sum(results.values())
    total_count = len(results)
    
    logger.info(f"\nCompleted: {success_count}/{total_count} phases")
    
    if success_count == total_count:
        logger.info("\n🎉 ALL PHASES COMPLETE! 🎉")
        logger.info("\nYour Stellantis Market Intelligence platform is fully operational.")
        logger.info("\nAccess at: http://localhost:8000")
    else:
        logger.warning("\n⚠ Some phases failed - check logs above")


if __name__ == '__main__':
    main()
