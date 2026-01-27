"""
Optimistic Locking Implementation for DRIMS
Uses version_nbr column to prevent concurrent modification conflicts
"""
from sqlalchemy.orm.exc import StaleDataError
from app.core.exceptions import OptimisticLockError
import logging

logger = logging.getLogger(__name__)


def setup_optimistic_locking(db):
    """
    Setup optimistic locking using SQLAlchemy's version_id_col feature.
    
    This ensures that all UPDATE operations on tables with version_nbr
    include the version number in the WHERE clause and increment it automatically.
    """
    
    from sqlalchemy import inspect
    from app.db import models
    
    configured_count = 0
    
    for model_name in dir(models):
        model_class = getattr(models, model_name)
        
        if not isinstance(model_class, type):
            continue
        
        if not hasattr(model_class, '__tablename__'):
            continue
        
        if not hasattr(model_class, 'version_nbr'):
            continue
        
        try:
            mapper_obj = inspect(model_class)
            
            for prop in mapper_obj.iterate_properties:
                if hasattr(prop, 'columns') and len(prop.columns) > 0:
                    col = prop.columns[0]
                    if col.name == 'version_nbr':
                        mapper_obj.version_id_col = col
                        configured_count += 1
                        logger.info(f"✓ Configured optimistic locking for {model_name}")
                        break
        except Exception as e:
            logger.warning(f"Could not configure optimistic locking for {model_name}: {e}")
    
    logger.info(f"Optimistic locking configured for {configured_count} models with version_nbr")
