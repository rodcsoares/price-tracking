"""SQLite database manager for price history tracking."""

import sqlite3
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# Default database path (relative to project root)
DEFAULT_DB_PATH = Path(__file__).parent.parent / "prices.db"


class PriceDatabase:
    """SQLite database for tracking item prices over time."""
    
    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self._init_db()
    
    @contextmanager
    def _get_connection(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
    
    def _init_db(self):
        """Initialize database schema if not exists."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Migration FIRST: check if old schema exists and migrate
            self._migrate_if_needed(cursor)
            
            # Items table - stores unique products from any retailer
            # Note: 'sku' is the unique identifier per source (ASIN for Amazon, SKU for others)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sku TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'amazon',
                    title TEXT NOT NULL,
                    url TEXT,
                    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(sku, source)
                )
            """)
            
            # Price history table - stores all price observations
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS price_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id INTEGER NOT NULL REFERENCES items(id),
                    price REAL NOT NULL,
                    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Indices for performance
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_price_history_item_id ON price_history(item_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_price_history_scraped_at ON price_history(scraped_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_items_sku_source ON items(sku, source)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_items_source ON items(source)")
            
            logger.info(f"Database initialized at {self.db_path}")
    
    def _migrate_if_needed(self, cursor):
        """Migrate old schema (with 'asin' column) to new schema (with 'sku' + 'source')."""
        # Check if we have the old schema
        cursor.execute("PRAGMA table_info(items)")
        columns = {row[1] for row in cursor.fetchall()}
        
        if 'asin' in columns and 'sku' not in columns:
            logger.info("Migrating database from old schema (asin) to new schema (sku + source)")
            
            # Create new table
            cursor.execute("""
                CREATE TABLE items_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sku TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'amazon',
                    title TEXT NOT NULL,
                    url TEXT,
                    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(sku, source)
                )
            """)
            
            # Copy data from old table
            cursor.execute("""
                INSERT INTO items_new (id, sku, source, title, url, first_seen, last_seen)
                SELECT id, asin, 'amazon', title, url, first_seen, last_seen FROM items
            """)
            
            # Replace old table
            cursor.execute("DROP TABLE items")
            cursor.execute("ALTER TABLE items_new RENAME TO items")
            
            # Recreate indices
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_items_sku_source ON items(sku, source)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_items_source ON items(source)")
            
            logger.info("Migration complete")
    
    def upsert_item(self, sku: str, title: str, source: str = "amazon", url: Optional[str] = None) -> int:
        """
        Insert or update an item. Returns the item ID.
        
        Args:
            sku: Unique identifier (ASIN for Amazon, product ID for others)
            title: Product title
            source: Retailer name (amazon, newegg, canadacomputers, memoryexpress)
            url: Product URL
        
        If item exists, updates last_seen timestamp.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Check if item exists (unique by sku + source)
            cursor.execute("SELECT id FROM items WHERE sku = ? AND source = ?", (sku, source))
            row = cursor.fetchone()
            
            if row:
                # Update last_seen
                cursor.execute(
                    "UPDATE items SET last_seen = ?, title = ?, url = COALESCE(?, url) WHERE id = ?",
                    (datetime.now(), title, url, row['id'])
                )
                return row['id']
            else:
                # Insert new item
                cursor.execute(
                    "INSERT INTO items (sku, source, title, url) VALUES (?, ?, ?, ?)",
                    (sku, source, title, url)
                )
                logger.debug(f"[{source}] New item: {sku} - {title[:50]}")
                return cursor.lastrowid
    
    def add_price(self, item_id: int, price: float) -> int:
        """Add a price observation for an item. Returns price_history ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO price_history (item_id, price) VALUES (?, ?)",
                (item_id, price)
            )
            return cursor.lastrowid
    
    def get_price_history(self, item_id: int, limit: int = 100) -> list[dict]:
        """
        Get price history for an item, most recent first.
        
        Returns list of dicts with 'price' and 'scraped_at' keys.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT price, scraped_at 
                FROM price_history 
                WHERE item_id = ? 
                ORDER BY scraped_at DESC 
                LIMIT ?
                """,
                (item_id, limit)
            )
            return [dict(row) for row in cursor.fetchall()]
    
    def get_all_prices_for_item(self, item_id: int) -> list[float]:
        """Get all historical prices for an item (oldest first, for stats)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT price FROM price_history WHERE item_id = ? ORDER BY scraped_at ASC",
                (item_id,)
            )
            return [row['price'] for row in cursor.fetchall()]
    
    def get_item_by_sku(self, sku: str, source: str = "amazon") -> Optional[dict]:
        """Get item details by SKU and source."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM items WHERE sku = ? AND source = ?", (sku, source))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def get_all_items(self) -> list[dict]:
        """Get all tracked items."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM items ORDER BY last_seen DESC")
            return [dict(row) for row in cursor.fetchall()]
    
    def get_item_count(self) -> int:
        """Get total number of tracked items."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as count FROM items")
            return cursor.fetchone()['count']
    
    def get_price_count(self) -> int:
        """Get total number of price observations."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as count FROM price_history")
            return cursor.fetchone()['count']
    
    def verify_schema(self) -> bool:
        """Verify database schema is correct. Returns True if valid."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # Check items table
                cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='items'")
                items_schema = cursor.fetchone()
                if not items_schema:
                    logger.error("Missing 'items' table")
                    return False
                
                # Check price_history table
                cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='price_history'")
                history_schema = cursor.fetchone()
                if not history_schema:
                    logger.error("Missing 'price_history' table")
                    return False
                
                logger.info("Database schema verified ✓")
                return True
                
        except Exception as e:
            logger.error(f"Schema verification failed: {e}")
            return False
