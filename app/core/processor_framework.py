"""
Generic Data Processor Framework

This module provides a framework for creating standardized data processors
that follow a consistent pattern: timestamp setup → rename → convert → validate.
"""

from typing import Dict, List, Optional, Callable
from dataclasses import dataclass
import logging

import numpy as np
import pandas as pd

from . import utils
from .processor_utils import initial_dataframe_setup, apply_common_processing

logger = logging.getLogger(__name__)


@dataclass
class ProcessorConfig:
    """
    Configuration for a data processor.
    
    This encapsulates the common parameters needed for data preprocessing.
    """
    timestamp_col: str = "Timestamp"
    rename_map: Dict[str, str] = None
    numeric_cols: List[str] = None
    expected_cols: Optional[List[str]] = None
    post_process_func: Optional[Callable[[pd.DataFrame], pd.DataFrame]] = None
    
    def __post_init__(self):
        """Initialize default values."""
        if self.rename_map is None:
            self.rename_map = {}
        if self.numeric_cols is None:
            self.numeric_cols = list(self.rename_map.values())
        if self.expected_cols is None:
            self.expected_cols = [self.timestamp_col] + list(self.rename_map.values())


class BaseDataProcessor:
    """
    Base class for data processors.
    
    Provides a standard pipeline: timestamp setup → rename → convert → validate.
    Subclasses can override methods to add custom processing steps.
    """
    
    def __init__(self, config: ProcessorConfig):
        """
        Initialize processor with configuration.
        
        Args:
            config: ProcessorConfig instance with processing parameters
        """
        self.config = config
    
    def process(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Process a DataFrame through the standard pipeline.
        
        Pipeline steps:
        1. Initial setup (timestamp standardization, UTC conversion, validation)
        2. Column renaming
        3. Numeric conversion
        4. Column validation (ensure expected columns exist)
        5. Post-processing (if configured)
        
        Args:
            df: Raw DataFrame to process
            
        Returns:
            Processed DataFrame
        """
        # Step 1: Initial setup (handles timestamp standardization)
        df_processed = initial_dataframe_setup(df, self.config.timestamp_col)
        
        if df_processed.empty:
            # Ensure schema consistency even for empty dataframes
            return self._ensure_schema_for_empty(df_processed)
        
        # Step 2-4: Apply common processing (rename, convert, validate)
        df_processed = apply_common_processing(
            df_processed,
            self.config.timestamp_col,
            self.config.rename_map,
            self.config.numeric_cols
        )
        
        # Step 5: Post-processing (custom logic)
        if self.config.post_process_func:
            df_processed = self.config.post_process_func(df_processed)
        
        return df_processed
    
    def _ensure_schema_for_empty(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Ensure expected columns exist even in empty DataFrames.
        
        Args:
            df: Empty DataFrame
            
        Returns:
            DataFrame with expected columns (empty but with correct schema)
        """
        for col in self.config.expected_cols:
            if col not in df.columns:
                if col == self.config.timestamp_col:
                    df[col] = pd.Series(dtype="datetime64[ns, UTC]")
                else:
                    df[col] = np.nan
        return df


class ProcessorRegistry:
    """
    Registry for data processors.
    
    Provides a centralized way to register and retrieve processors by report type.
    """
    
    def __init__(self):
        self._processors: Dict[str, Callable[[pd.DataFrame], pd.DataFrame]] = {}
    
    def register(
        self,
        report_type: str,
        processor: Callable[[pd.DataFrame], pd.DataFrame]
    ):
        """
        Register a processor function for a report type.
        
        Args:
            report_type: Type of report (e.g., 'power', 'ctd')
            processor: Function that takes a DataFrame and returns a processed DataFrame
        """
        self._processors[report_type] = processor
        logger.debug(f"Registered processor for report type: {report_type}")
    
    def get(self, report_type: str) -> Optional[Callable[[pd.DataFrame], pd.DataFrame]]:
        """
        Get a processor for a report type.
        
        Args:
            report_type: Type of report
            
        Returns:
            Processor function or None if not found
        """
        return self._processors.get(report_type)
    
    def has(self, report_type: str) -> bool:
        """
        Check if a processor is registered for a report type.
        
        Args:
            report_type: Type of report
            
        Returns:
            True if processor is registered, False otherwise
        """
        return report_type in self._processors
    
    def list_types(self) -> List[str]:
        """
        List all registered report types.
        
        Returns:
            List of registered report type names
        """
        return list(self._processors.keys())


# Global processor registry instance
_processor_registry = ProcessorRegistry()


def get_processor_registry() -> ProcessorRegistry:
    """
    Get the global processor registry.
    
    Returns:
        ProcessorRegistry instance
    """
    return _processor_registry


def register_processor(
    report_type: str,
    processor: Callable[[pd.DataFrame], pd.DataFrame]
):
    """
    Convenience function to register a processor.
    
    Args:
        report_type: Type of report
        processor: Processor function
    """
    _processor_registry.register(report_type, processor)


def get_processor(report_type: str) -> Optional[Callable[[pd.DataFrame], pd.DataFrame]]:
    """
    Convenience function to get a processor.
    
    Args:
        report_type: Type of report
        
    Returns:
        Processor function or None if not found
    """
    return _processor_registry.get(report_type)

