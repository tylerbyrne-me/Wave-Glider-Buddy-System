"""
Service Template for Wave Glider Buddy System

This template provides a standard structure for creating new services.
Services contain business logic that doesn't belong in routers or core modules.

Usage:
1. Copy this template to app/services/your_service_name.py
2. Replace placeholder names and add your business logic
3. Follow the patterns established here
"""

import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

from sqlmodel import Session as SQLModelSession
from pandas import DataFrame

from ..core import models
from ..core.error_handlers import handle_processing_error, ErrorContext

logger = logging.getLogger(__name__)


class YourService:
    """
    Service for [domain/feature] operations.
    
    This service handles [description of what this service does].
    Services should contain business logic that:
    - Orchestrates multiple core operations
    - Handles complex domain-specific calculations
    - Coordinates between multiple data sources
    - Contains logic that would make routers too large
    
    Services should NOT contain:
    - Simple CRUD operations (use routers directly)
    - Data loading (use data_service)
    - Simple validation (use Pydantic models)
    - Shared utilities (use core/utils)
    """
    
    def __init__(self, db_session: SQLModelSession):
        """
        Initialize service with database session.
        
        Args:
            db_session: SQLModel database session
        """
        self.db_session = db_session
    
    def process_data(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Example method that processes data.
        
        This method demonstrates:
        - Type hints for all parameters and return values
        - Error handling using error_handlers
        - Logging for important operations
        - Clear documentation
        
        Args:
            input_data: Dictionary containing input parameters
            
        Returns:
            Dictionary with processed results
            
        Raises:
            HTTPException: If processing fails
        """
        try:
            logger.info(f"Processing data: {input_data}")
            
            # Your business logic here
            # Example: coordinate multiple operations
            result = {
                "status": "success",
                "processed_at": datetime.now(timezone.utc).isoformat(),
                "data": input_data
            }
            
            logger.info("Data processed successfully")
            return result
            
        except ValueError as e:
            # Use error handlers for consistent error responses
            raise handle_processing_error(
                operation="processing data",
                error=e,
                context=ErrorContext(
                    operation="process_data",
                    resource=str(input_data),
                )
            )
        except Exception as e:
            # Catch-all for unexpected errors
            raise handle_processing_error(
                operation="processing data",
                error=e,
                context=ErrorContext(
                    operation="process_data",
                    resource=str(input_data),
                )
            )
    
    def calculate_metrics(self, mission_id: str) -> Dict[str, float]:
        """
        Example method that calculates domain-specific metrics.
        
        Args:
            mission_id: Mission identifier
            
        Returns:
            Dictionary with calculated metrics
        """
        try:
            logger.info(f"Calculating metrics for mission: {mission_id}")
            
            # Example: complex calculation logic
            metrics = {
                "metric1": 0.0,
                "metric2": 0.0,
            }
            
            return metrics
            
        except Exception as e:
            raise handle_processing_error(
                operation="calculating metrics",
                error=e,
                context=ErrorContext(
                    operation="calculate_metrics",
                    resource=mission_id,
                )
            )
    
    def get_aggregated_data(self, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Example method that aggregates data from multiple sources.
        
        Args:
            filters: Dictionary of filter criteria
            
        Returns:
            List of aggregated data dictionaries
        """
        try:
            logger.info(f"Getting aggregated data with filters: {filters}")
            
            # Example: coordinate multiple data operations
            aggregated = []
            
            return aggregated
            
        except Exception as e:
            raise handle_processing_error(
                operation="aggregating data",
                error=e,
                context=ErrorContext(
                    operation="get_aggregated_data",
                    resource=str(filters),
                )
            )


# ============================================================================
# Standalone Service Functions (Alternative Pattern)
# ============================================================================
# Some services may be function-based rather than class-based.
# Use this pattern when the service doesn't need to maintain state.

def process_data_standalone(
    db_session: SQLModelSession,
    input_data: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Standalone service function example.
    
    Use this pattern when:
    - Service doesn't need to maintain state
    - Operations are simple and don't require class structure
    - Function is stateless
    
    Args:
        db_session: Database session (passed as parameter)
        input_data: Input data dictionary
        
    Returns:
        Processed data dictionary
    """
    try:
        logger.info(f"Processing data: {input_data}")
        
        # Your business logic here
        result = {
            "status": "success",
            "data": input_data
        }
        
        return result
        
    except Exception as e:
        raise handle_processing_error(
            operation="processing data",
            error=e,
            context=ErrorContext(
                operation="process_data_standalone",
                resource=str(input_data),
            )
        )

