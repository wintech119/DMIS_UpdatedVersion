"""
DRIMS Custom Exceptions
"""

class OptimisticLockError(Exception):
    """
    Raised when an optimistic locking conflict occurs.
    This happens when a record is modified by another transaction
    between the time it was read and when it's being updated.
    """
    def __init__(self, model_name, record_id, message=None):
        self.model_name = model_name
        self.record_id = record_id
        if message is None:
            message = (
                f"Optimistic locking conflict: {model_name} with ID {record_id} "
                f"was modified by another transaction. Please refresh and try again."
            )
        super().__init__(message)
