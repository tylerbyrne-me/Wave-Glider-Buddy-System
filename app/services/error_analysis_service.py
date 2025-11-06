"""
Error Analysis Service
Handles error classification, trend analysis, and reporting
"""

import pandas as pd
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional, Tuple
from sqlmodel import Session, select, func, and_, or_

from .error_classification_service import ErrorClassifier
from ..core.error_types import ErrorCategory
from ..core.models.error_analysis import (
    ClassifiedError, ErrorCategoryStats, ErrorPattern,
    ErrorCategoryEnum, ErrorSeverityEnum, ErrorTrendData, ErrorDashboardSummary
)
from ..core.processors import preprocess_error_df

class ErrorAnalysisService:
    """Service for analyzing and tracking error data"""
    
    def __init__(self, db_session: Session):
        self.db_session = db_session
        self.classifier = ErrorClassifier()
    
    def process_error_dataframe(self, error_df: pd.DataFrame, mission_id: str) -> List[ClassifiedError]:
        """
        Process a raw error dataframe and classify all errors
        
        Args:
            error_df: Raw error data from CSV
            mission_id: Mission identifier
            
        Returns:
            List of classified error objects
        """
        # Preprocess the dataframe using existing logic
        processed_df = preprocess_error_df(error_df)
        
        if processed_df.empty:
            return []
        
        classified_errors = []
        
        for _, row in processed_df.iterrows():
            # Extract data from row
            timestamp = row.get('Timestamp')
            vehicle_name = str(row.get('VehicleName', 'Unknown'))
            original_message = str(row.get('ErrorMessage', ''))
            self_corrected = row.get('SelfCorrected', False)
            
            # Skip invalid entries
            if pd.isna(timestamp) or not original_message.strip():
                continue
            
            # Classify the error
            category, confidence, description = self.classifier.classify_error(original_message)
            
            # Determine severity based on category and confidence
            severity = self._determine_severity(category, confidence, self_corrected)
            
            # Create classified error object
            classified_error = ClassifiedError(
                mission_id=mission_id,
                timestamp=timestamp,
                vehicle_name=vehicle_name,
                original_message=original_message,
                error_category=ErrorCategoryEnum(category.value),
                classification_confidence=confidence,
                severity_level=ErrorSeverityEnum(severity),
                category_description=description,
                self_corrected=bool(self_corrected) if not pd.isna(self_corrected) else None
            )
            
            classified_errors.append(classified_error)
        
        return classified_errors
    
    def _determine_severity(self, category: ErrorCategory, confidence: float, self_corrected: bool) -> int:
        """Determine error severity based on category, confidence, and self-correction"""
        base_severity = {
            ErrorCategory.NAVIGATION: 2,
            ErrorCategory.COMMUNICATION: 1,
            ErrorCategory.SYSTEM_OPS: 2,
            ErrorCategory.ENVIRONMENTAL: 1,
            ErrorCategory.UNKNOWN: 1
        }.get(category, 1)
        
        # Adjust based on confidence
        if confidence < 0.5:
            base_severity = max(1, base_severity - 1)
        elif confidence > 0.9:
            base_severity = min(3, base_severity + 1)
        
        # Adjust based on self-correction
        if self_corrected:
            base_severity = max(1, base_severity - 1)
        
        return base_severity
    
    def save_classified_errors(self, classified_errors: List[ClassifiedError]) -> int:
        """Save classified errors to database"""
        for error in classified_errors:
            self.db_session.add(error)
        
        self.db_session.commit()
        return len(classified_errors)
    
    def get_error_trends(self, mission_id: str, days_back: int = 30) -> List[ErrorTrendData]:
        """Get error trend data for a mission"""
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_back)
        
        # Query classified errors
        stmt = select(ClassifiedError).where(
            and_(
                ClassifiedError.mission_id == mission_id,
                ClassifiedError.timestamp >= cutoff_date
            )
        )
        
        errors = self.db_session.exec(stmt).all()
        
        if not errors:
            return []
        
        # Group by day and category
        df = pd.DataFrame([{
            'timestamp': error.timestamp,
            'category': error.error_category,
            'self_corrected': error.self_corrected,
            'confidence': error.classification_confidence
        } for error in errors])
        
        df['date'] = df['timestamp'].dt.date
        df['self_corrected'] = df['self_corrected'].fillna(False)
        
        # Calculate daily trends
        daily_trends = []
        for date in df['date'].unique():
            day_data = df[df['date'] == date]
            
            for category in day_data['category'].unique():
                category_data = day_data[day_data['category'] == category]
                
                trend_data = ErrorTrendData(
                    time_period=date.isoformat(),
                    category=ErrorCategoryEnum(category),
                    error_count=len(category_data),
                    self_correction_rate=category_data['self_corrected'].mean() * 100,
                    avg_confidence=category_data['confidence'].mean()
                )
                
                daily_trends.append(trend_data)
        
        return sorted(daily_trends, key=lambda x: x.time_period)
    
    def get_dashboard_summary(self, mission_id: str) -> ErrorDashboardSummary:
        """Get error summary for dashboard display"""
        # Get all errors for mission
        stmt = select(ClassifiedError).where(ClassifiedError.mission_id == mission_id)
        all_errors = self.db_session.exec(stmt).all()
        
        if not all_errors:
            return ErrorDashboardSummary(
                total_errors=0,
                recent_errors=0,
                category_breakdown={},
                top_error_types=[],
                self_correction_rate=0.0,
                trend_direction="stable"
            )
        
        # Calculate recent errors (last 24 hours)
        recent_cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        recent_errors = [e for e in all_errors if e.timestamp >= recent_cutoff]
        
        # Category breakdown
        category_counts = {}
        for error in all_errors:
            cat = error.error_category.value
            category_counts[cat] = category_counts.get(cat, 0) + 1
        
        # Self-correction rate
        self_corrected_count = sum(1 for e in all_errors if e.self_corrected)
        self_correction_rate = (self_corrected_count / len(all_errors)) * 100 if all_errors else 0
        
        # Top error types (by frequency)
        top_error_types = []
        for error in all_errors:
            message = error.original_message
            # Find existing entry or create new
            existing = next((item for item in top_error_types if item['message'] == message), None)
            if existing:
                existing['count'] += 1
            else:
                top_error_types.append({
                    'message': message,
                    'category': error.error_category.value,
                    'count': 1,
                    'self_corrected': error.self_corrected
                })
        
        # Sort by count and take top 5
        top_error_types = sorted(top_error_types, key=lambda x: x['count'], reverse=True)[:5]
        
        # Determine trend direction (simplified)
        if len(recent_errors) > len(all_errors) * 0.1:  # More than 10% of errors are recent
            trend_direction = "increasing"
        elif len(recent_errors) < len(all_errors) * 0.05:  # Less than 5% are recent
            trend_direction = "decreasing"
        else:
            trend_direction = "stable"
        
        return ErrorDashboardSummary(
            total_errors=len(all_errors),
            recent_errors=len(recent_errors),
            category_breakdown=category_counts,
            top_error_types=top_error_types,
            self_correction_rate=self_correction_rate,
            trend_direction=trend_direction
        )
    
    def analyze_error_patterns(self, mission_id: str) -> Dict:
        """Analyze error patterns for a mission"""
        stmt = select(ClassifiedError).where(ClassifiedError.mission_id == mission_id)
        errors = self.db_session.exec(stmt).all()
        
        if not errors:
            return {"message": "No error data available"}
        
        # Extract error messages for analysis
        error_messages = [error.original_message for error in errors]
        
        # Use the classifier to analyze patterns
        analysis = self.classifier.get_error_statistics(error_messages)
        
        # Add mission-specific metadata
        analysis['mission_id'] = mission_id
        analysis['analysis_timestamp'] = datetime.now(timezone.utc).isoformat()
        
        return analysis
