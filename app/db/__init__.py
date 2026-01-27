"""
Database configuration and session management
"""
from flask_sqlalchemy import SQLAlchemy
from app.core.optimistic_locking import setup_optimistic_locking

db = SQLAlchemy()

def init_db(app):
    """Initialize database with Flask app"""
    db.init_app(app)
    
    with app.app_context():
        setup_optimistic_locking(db)
    
    return db
