import sqlite3
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

log = logging.getLogger("PEAK-DB")
DB_PATH = Path("peak_agency.db")

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    conn = get_conn()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS customers (
                telegram_id INTEGER PRIMARY KEY,
                username TEXT, full_name TEXT,
                business_type TEXT, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER NOT NULL, product_id TEXT NOT NULL,
                product_name TEXT NOT NULL, amount_usd REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                tx_id TEXT, payment_url TEXT, created_at TEXT NOT NULL,
                paid_at TEXT, delivered_at TEXT,
                FOREIGN KEY (customer_id) REFERENCES customers(telegram_id)
            );
            CREATE TABLE IF NOT EXISTS followups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL, customer_id INTEGER NOT NULL,
                scheduled_at TEXT NOT NULL, sent_at TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                FOREIGN KEY (order_id) REFERENCES orders(id)
            );
        """)
        conn.commit()
    finally:
        conn.close()

def upsert_customer(telegram_id, username, full_name, business_type=None):
    conn = get_conn()
    try:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("""
            INSERT INTO customers (telegram_id, username, full_name, business_type, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                username=excluded.username, full_name=excluded.full_name,
                business_type=COALESCE(excluded.business_type, customers.business_type)
        """, (telegram_id, username, full_name, business_type, now))
        conn.commit()
    finally:
        conn.close()

def set_business_type(telegram_id, business_type):
    conn = get_conn()
    try:
        conn.execute("UPDATE customers SET business_type=? WHERE telegram_id=?", (business_type, telegram_id))
        conn.commit()
    finally:
        conn.close()

def get_customer(telegram_id):
    conn = get_conn()
    try:
        return conn.execute("SELECT * FROM customers WHERE telegram_id=?", (telegram_id,)).fetchone()
    finally:
        conn.close()

def create_order(customer_id, product_id, product_name, amount_usd, payment_url):
    conn = get_conn()
    try:
        now = datetime.now(timezone.utc).isoformat()
        cur = conn.execute("""
            INSERT INTO orders (customer_id, product_id, product_name, amount_usd, status, payment_url, created_at)
            VALUES (?, ?, ?, ?, 'pending', ?, ?)
        """, (customer_id, product_id, product_name, amount_usd, payment_url, now))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()

def get_pending_orders_for_amount(amount_usd):
    conn = get_conn()
    try:
        return conn.execute("""
            SELECT o.*, c.telegram_id, c.full_name FROM orders o
            JOIN customers c ON o.customer_id=c.telegram_id
            WHERE o.status='pending' AND ABS(o.amount_usd - ?) < 2.0
            ORDER BY o.created_at ASC LIMIT 1
        """, (amount_usd,)).fetchall()
    finally:
        conn.close()

def mark_order_paid(order_id, tx_id):
    conn = get_conn()
    try:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("UPDATE orders SET status='paid', tx_id=?, paid_at=? WHERE id=?", (tx_id, now, order_id))
        conn.commit()
    finally:
        conn.close()

def mark_order_delivered(order_id):
    conn = get_conn()
    try:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("UPDATE orders SET status='delivered', delivered_at=? WHERE id=?", (now, order_id))
        conn.commit()
    finally:
        conn.close()

def schedule_followup(order_id, customer_id, days=7):
    conn = get_conn()
    try:
        scheduled = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
        conn.execute("INSERT INTO followups (order_id, customer_id, scheduled_at, status) VALUES (?, ?, ?, 'pending')",
                     (order_id, customer_id, scheduled))
        conn.commit()
    finally:
        conn.close()

def get_due_followups():
    conn = get_conn()
    try:
        now = datetime.now(timezone.utc).isoformat()
        return conn.execute("""
            SELECT f.*, o.product_name, o.amount_usd FROM followups f
            JOIN orders o ON f.order_id=o.id
            WHERE f.status='pending' AND f.scheduled_at <= ?
        """, (now,)).fetchall()
    finally:
        conn.close()

def mark_followup_sent(followup_id):
    conn = get_conn()
    try:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("UPDATE followups SET status='sent', sent_at=? WHERE id=?", (now, followup_id))
        conn.commit()
    finally:
        conn.close()

def mark_followup_failed(followup_id):
    conn = get_conn()
    try:
        conn.execute("UPDATE followups SET status='failed' WHERE id=?", (followup_id,))
        conn.commit()
    finally:
        conn.close()
