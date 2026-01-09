"""
Reset database - drops all tables and recreates them
"""
import os
from app import app, db

# Remove old database file
db_path = 'synergy_lms.db'
if os.path.exists(db_path):
    os.remove(db_path)
    print(f"[OK] Removed old database: {db_path}")

# Create new tables with updated schema
with app.app_context():
    db.create_all()
    print("[OK] Created new database with updated schema")

print("\n[SUCCESS] Database reset complete! You can now run: python app.py")
