"""
Error plotting service - consolidated plotting functions
Handles all error visualization needs
"""

import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
from typing import Dict, List, Tuple
import seaborn as sns
from ..routers.error_analysis_models import ErrorTrendData

# Trend plotting functions
def plot_error_trends(trend_data: List[ErrorTrendData], mission_id: str, 
                     figsize: Tuple[int, int] = (12, 8)) -> plt.Figure:
    """Create a comprehensive error trends plot"""
    if not trend_data:
        fig, ax = plt.subplots(figsize=figsize)
        ax.text(0.5, 0.5, 'No error trend data available', 
                ha='center', va='center', fontsize=16)
        ax.set_title(f'Error Trends - Mission {mission_id}')
        return fig
    
    # Convert to DataFrame for easier plotting
    df = pd.DataFrame([{
        'date': pd.to_datetime(trend.time_period),
        'category': trend.category.value,
        'error_count': trend.error_count,
        'self_correction_rate': trend.self_correction_rate,
        'avg_confidence': trend.avg_confidence
    } for trend in trend_data])
    
    fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=figsize)
    
    # Plot 1: Error count over time by category
    for category in df['category'].unique():
        cat_data = df[df['category'] == category]
        ax1.plot(cat_data['date'], cat_data['error_count'], 
                label=category.title(), marker='o')
    ax1.set_title('Error Count Over Time')
    ax1.set_ylabel('Error Count')
    ax1.legend()
    ax1.tick_params(axis='x', rotation=45)
    
    # Plot 2: Self-correction rate over time
    for category in df['category'].unique():
        cat_data = df[df['category'] == category]
        ax2.plot(cat_data['date'], cat_data['self_correction_rate'], 
                label=category.title(), marker='s')
    ax2.set_title('Self-Correction Rate Over Time')
    ax2.set_ylabel('Self-Correction Rate')
    ax2.legend()
    ax2.tick_params(axis='x', rotation=45)
    
    # Plot 3: Average confidence over time
    for category in df['category'].unique():
        cat_data = df[df['category'] == category]
        ax3.plot(cat_data['date'], cat_data['avg_confidence'], 
                label=category.title(), marker='^')
    ax3.set_title('Classification Confidence Over Time')
    ax3.set_ylabel('Average Confidence')
    ax3.legend()
    ax3.tick_params(axis='x', rotation=45)
    
    # Plot 4: Total errors by category (pie chart)
    category_totals = df.groupby('category')['error_count'].sum()
    ax4.pie(category_totals.values, labels=category_totals.index, autopct='%1.1f%%')
    ax4.set_title('Total Errors by Category')
    
    plt.tight_layout()
    return fig

def plot_error_timeline(error_data: pd.DataFrame, mission_id: str) -> plt.Figure:
    """Create a timeline plot of individual errors"""
    fig, ax = plt.subplots(figsize=(15, 6))
    
    # Create timeline plot
    for i, (_, error) in enumerate(error_data.iterrows()):
        color = 'red' if not error.get('self_corrected', False) else 'green'
        ax.scatter(error['timestamp'], i, c=color, alpha=0.6, s=20)
    
    ax.set_title(f'Error Timeline - Mission {mission_id}')
    ax.set_xlabel('Time')
    ax.set_ylabel('Error Index')
    ax.tick_params(axis='x', rotation=45)
    
    return fig

# Heatmap plotting functions
def plot_error_heatmap(trend_data: List[ErrorTrendData], mission_id: str) -> plt.Figure:
    """Create error frequency heatmap by hour and category"""
    if not trend_data:
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.text(0.5, 0.5, 'No error data available for heatmap', 
                ha='center', va='center', fontsize=16)
        return fig
    
    # Convert trend data to DataFrame
    df = pd.DataFrame([{
        'date': pd.to_datetime(trend.time_period),
        'category': trend.category.value,
        'error_count': trend.error_count,
        'self_correction_rate': trend.self_correction_rate,
        'avg_confidence': trend.avg_confidence
    } for trend in trend_data])
    
    # Prepare data for heatmap
    df['hour'] = df['date'].dt.hour
    df['category'] = df.get('category', 'unknown')
    
    # Create pivot table
    heatmap_data = df.groupby(['hour', 'category']).size().unstack(fill_value=0)
    
    fig, ax = plt.subplots(figsize=(12, 8))
    sns.heatmap(heatmap_data, annot=True, fmt='d', cmap='YlOrRd', ax=ax)
    ax.set_title(f'Error Frequency Heatmap - Mission {mission_id}')
    ax.set_xlabel('Error Category')
    ax.set_ylabel('Hour of Day')
    
    plt.tight_layout()
    return fig

def plot_confidence_heatmap(error_data: pd.DataFrame, mission_id: str) -> plt.Figure:
    """Create confidence level heatmap"""
    if error_data.empty:
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.text(0.5, 0.5, 'No error data available for confidence heatmap', 
                ha='center', va='center', fontsize=16)
        return fig
    
    # Prepare data
    error_data['hour'] = error_data['timestamp'].dt.hour
    error_data['category'] = error_data.get('category', 'unknown')
    error_data['confidence'] = error_data.get('confidence', 0.0)
    
    # Create pivot table with mean confidence
    heatmap_data = error_data.groupby(['hour', 'category'])['confidence'].mean().unstack(fill_value=0)
    
    fig, ax = plt.subplots(figsize=(12, 8))
    sns.heatmap(heatmap_data, annot=True, fmt='.2f', cmap='RdYlGn', ax=ax)
    ax.set_title(f'Classification Confidence Heatmap - Mission {mission_id}')
    ax.set_xlabel('Error Category')
    ax.set_ylabel('Hour of Day')
    
    plt.tight_layout()
    return fig

def plot_error_summary_dashboard(summary_data, mission_id: str) -> plt.Figure:
    """Create comprehensive error summary dashboard"""
    fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(15, 10))
    
    # Plot 1: Total errors over time (simplified)
    if hasattr(summary_data, 'total_errors'):
        ax1.bar(['Total Errors'], [summary_data.total_errors])
    ax1.set_title('Total Error Count')
    ax1.set_ylabel('Error Count')
    
    # Plot 2: Category distribution
    if hasattr(summary_data, 'category_breakdown') and summary_data.category_breakdown:
        categories = list(summary_data.category_breakdown.keys())
        counts = list(summary_data.category_breakdown.values())
        ax2.pie(counts, labels=categories, autopct='%1.1f%%')
    ax2.set_title('Error Categories')
    
    # Plot 3: Self-correction rate
    if hasattr(summary_data, 'self_correction_rate'):
        correction_rate = summary_data.self_correction_rate
        ax3.bar(['Self-Corrected', 'Not Self-Corrected'], 
                [correction_rate, 100-correction_rate], 
                color=['green', 'red'])
    ax3.set_title('Self-Correction Rate')
    ax3.set_ylabel('Percentage')
    
    # Plot 4: Recent vs Total errors
    if hasattr(summary_data, 'recent_errors') and hasattr(summary_data, 'total_errors'):
        recent = summary_data.recent_errors
        total = summary_data.total_errors
        ax4.bar(['Recent (24h)', 'Total'], [recent, total], color=['orange', 'blue'])
    ax4.set_title('Recent vs Total Errors')
    ax4.set_ylabel('Error Count')
    
    plt.suptitle(f'Error Analysis Dashboard - Mission {mission_id}', fontsize=16)
    plt.tight_layout()
    return fig

# Distribution plotting functions
def plot_error_distribution(category_data: Dict, mission_id: str, 
                          figsize: Tuple[int, int] = (10, 6)) -> plt.Figure:
    """Create error distribution charts"""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=figsize)
    
    # Pie chart
    categories = list(category_data.keys())
    counts = [data['count'] for data in category_data.values()]
    colors = ['#0d6efd', '#ffc107', '#dc3545', '#0dcaf0', '#6c757d']
    
    ax1.pie(counts, labels=categories, autopct='%1.1f%%', colors=colors[:len(categories)])
    ax1.set_title(f'Error Distribution - Mission {mission_id}')
    
    # Bar chart
    ax2.bar(categories, counts, color=colors[:len(categories)])
    ax2.set_title('Error Count by Category')
    ax2.set_ylabel('Error Count')
    ax2.tick_params(axis='x', rotation=45)
    
    plt.tight_layout()
    return fig

def plot_category_breakdown(category_data: Dict, mission_id: str) -> plt.Figure:
    """Create detailed category breakdown"""
    fig, ax = plt.subplots(figsize=(12, 8))
    
    categories = list(category_data.keys())
    counts = [data['count'] for data in category_data.values()]
    confidences = [data['confidence_avg'] for data in category_data.values()]
    
    # Create grouped bar chart
    x = range(len(categories))
    width = 0.35
    
    bars1 = ax.bar([i - width/2 for i in x], counts, width, label='Error Count', alpha=0.8)
    ax2 = ax.twinx()
    bars2 = ax2.bar([i + width/2 for i in x], confidences, width, label='Avg Confidence', alpha=0.8, color='orange')
    
    ax.set_xlabel('Categories')
    ax.set_ylabel('Error Count', color='blue')
    ax2.set_ylabel('Average Confidence', color='orange')
    ax.set_title(f'Category Breakdown - Mission {mission_id}')
    ax.set_xticks(x)
    ax.set_xticklabels(categories, rotation=45)
    
    # Add value labels on bars
    for bar in bars1:
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2., height,
                f'{int(height)}', ha='center', va='bottom')
    
    for bar in bars2:
        height = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width()/2., height,
                f'{height:.2f}', ha='center', va='bottom')
    
    plt.tight_layout()
    return fig
