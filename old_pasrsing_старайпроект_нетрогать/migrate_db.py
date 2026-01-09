#!/usr/bin/env python3
"""
Database migration script for Synergy LMS Web Application
"""

import sqlite3
import os
from datetime import datetime

def migrate_database():
    """Apply database migrations"""
    db_path = 'instance/synergy_lms.db'
    
    if not os.path.exists(db_path):
        print(f"Database {db_path} not found. Creating new database...")
        return
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Check if number column exists in semesters table
        cursor.execute("PRAGMA table_info(semesters)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'number' not in columns:
            print("Adding 'number' column to semesters table...")
            cursor.execute("ALTER TABLE semesters ADD COLUMN number INTEGER;")
            print("[OK] Added 'number' column to semesters table")
        else:
            print("[OK] 'number' column already exists in semesters table")
        
        # Check if duration_seconds column exists in materials table
        cursor.execute("PRAGMA table_info(materials)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'duration_seconds' not in columns:
            print("Adding 'duration_seconds' column to materials table...")
            cursor.execute("ALTER TABLE materials ADD COLUMN duration_seconds INTEGER;")
            print("[OK] Added 'duration_seconds' column to materials table")
        else:
            print("[OK] 'duration_seconds' column already exists in materials table")
        
        # Check if is_completed column exists in materials table
        if 'is_completed' not in columns:
            print("Adding 'is_completed' column to materials table...")
            cursor.execute("ALTER TABLE materials ADD COLUMN is_completed BOOLEAN DEFAULT 0;")
            print("[OK] Added 'is_completed' column to materials table")
        else:
            print("[OK] 'is_completed' column already exists in materials table")
        
        conn.commit()
        print("\n[SUCCESS] Database migration completed successfully!")
        
    except Exception as e:
        print(f"[ERROR] Migration failed: {e}")
        conn.rollback()
    finally:
        conn.close()

def show_schema():
    """Show current database schema"""
    db_path = 'instance/synergy_lms.db'
    
    if not os.path.exists(db_path):
        print(f"Database {db_path} not found.")
        return
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    print("Current database schema:")
    print("=" * 50)
    
    # Get all tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    
    for table in tables:
        table_name = table[0]
        print(f"\nTable: {table_name}")
        print("-" * 30)
        
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = cursor.fetchall()
        
        for col in columns:
            col_id, name, type_name, not_null, default_val, pk = col
            nullable = "NOT NULL" if not_null else "NULL"
            primary = "PRIMARY KEY" if pk else ""
            default = f"DEFAULT {default_val}" if default_val else ""
            
            print(f"  {name} {type_name} {nullable} {default} {primary}".strip())
    
    conn.close()

if __name__ == '__main__':
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == 'schema':
        show_schema()
    else:
        migrate_database()
