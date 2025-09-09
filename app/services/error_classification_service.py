"""
Simplified Error Classification System
Refactored for better maintainability and performance
"""

import re
from typing import Dict, List, Optional, Tuple
from ..core.error_types import ErrorCategory, ErrorPattern

class ErrorClassifier:
    """Optimized error classifier with compiled patterns"""
    
    def __init__(self):
        from .error_patterns_service import ALL_PATTERNS
        self.patterns = ALL_PATTERNS
        self.compiled_patterns = self._compile_patterns()
    
    def _compile_patterns(self) -> List[Tuple[re.Pattern, ErrorPattern]]:
        """Pre-compile regex patterns for better performance"""
        return [
            (re.compile(pattern.pattern), pattern) 
            for pattern in self.patterns
        ]
    
    def classify_error(self, error_message: str) -> Tuple[ErrorCategory, float, str]:
        """
        Classify a single error message
        
        Args:
            error_message: The error message to classify
            
        Returns:
            Tuple of (category, confidence, description)
        """
        if not error_message or not error_message.strip():
            return ErrorCategory.UNKNOWN, 0.0, "Empty error message"
        
        error_message = error_message.strip()
        message_length = len(error_message)
        
        # Try each compiled pattern
        for compiled_pattern, pattern in self.compiled_patterns:
            match = compiled_pattern.search(error_message)
            if match:
                # Calculate confidence based on match quality
                match_length = len(match.group())
                if match_length / message_length > 0.5:
                    confidence = match_length / message_length
                else:
                    confidence = min(0.8, 0.3 + (match_length / 20))
                
                if confidence >= pattern.confidence_threshold:
                    return pattern.category, confidence, pattern.description
        
        return ErrorCategory.UNKNOWN, 0.0, "No matching pattern found"

    def get_error_statistics(self, error_messages: List[str]) -> Dict:
        """
        Analyze a list of error messages and return summary statistics
        
        Args:
            error_messages: List of error message strings
            
        Returns:
            Dictionary with analysis results
        """
        if not error_messages:
            return {
                'total_errors': 0,
                'categories': {},
                'category_distribution': {}
            }
        
        categories = {}
        total_errors = len(error_messages)
        
        # Initialize category data
        for category in ErrorCategory:
            categories[category.value] = {
                'count': 0,
                'confidence_avg': 0.0,
                'examples': []
            }
        
        # Classify each message
        for message in error_messages:
            category, confidence, description = self.classify_error(message)
            category_name = category.value
            
            categories[category_name]['count'] += 1
            categories[category_name]['confidence_avg'] += confidence
            
            # Store example messages (up to 3 per category)
            if len(categories[category_name]['examples']) < 3:
                categories[category_name]['examples'].append({
                    'message': message,
                    'confidence': confidence
                })
        
        # Calculate average confidence for each category
        for category_data in categories.values():
            if category_data['count'] > 0:
                category_data['confidence_avg'] = (
                    category_data['confidence_avg'] / category_data['count']
                )
        
        return {
            'total_errors': total_errors,
            'categories': categories,
            'category_distribution': {
                cat: data['count'] / total_errors * 100 
                for cat, data in categories.items()
            }
        }

def analyze_error_messages(error_messages: List[str]) -> Dict:
    """
    Analyze a list of error messages and return summary statistics
    
    Args:
        error_messages: List of error message strings
        
    Returns:
        Dictionary with analysis results
    """
    classifier = ErrorClassifier()
    return classifier.get_error_statistics(error_messages)

# Convenience functions for easy import
def classify_error_message(error_message: str) -> Tuple[ErrorCategory, float, str]:
    """Simple function to classify a single error message"""
    classifier = ErrorClassifier()
    return classifier.classify_error(error_message)
