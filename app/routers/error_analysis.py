"""
API endpoints for error analysis and tracking
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlmodel import Session
from typing import List, Optional
from datetime import datetime, timezone, timedelta
import io
import csv

from ..core.db import get_db_session
from ..core.auth import get_current_active_user, get_current_admin_user
from ..core.models import User
from ..services.error_analysis_service import ErrorAnalysisService
from ..core.models.error_analysis import ErrorDashboardSummary, ErrorTrendData
from ..services.error_classification_service import classify_error_message, analyze_error_messages
from ..services.error_plotting_service import (
    plot_error_trends, plot_error_heatmap, plot_error_summary_dashboard, 
    plot_error_timeline
)
import io
import base64
import matplotlib
import asyncio
from ..core import loaders
from ..core.data_service import get_data_service
from ..core.error_handlers import handle_processing_error, ErrorContext
from ..config import settings
import matplotlib.pyplot as plt
matplotlib.use('Agg')  # Use non-interactive backend

router = APIRouter(prefix="/api/errors", tags=["error-analysis"])


@router.get("/classify")
async def classify_error(
    error_message: str = Query(..., description="Error message to classify"),
    current_user: User = Depends(get_current_active_user)
):
    """Classify a single error message"""
    try:
        category, confidence, description = classify_error_message(error_message)
        return {
            "original_message": error_message,
            "category": category.value,
            "confidence": confidence,
            "description": description
        }
    except HTTPException:
        raise
    except Exception as e:
        raise handle_processing_error(
            operation="classifying error message",
            error=e,
            user_id=str(current_user.id) if current_user else None
        )

@router.get("/analyze/{mission_id}")
async def analyze_mission_errors(
    mission_id: str,
    current_user: User = Depends(get_current_active_user),
    session: Session = Depends(get_db_session)
):
    """Analyze error patterns for a specific mission"""
    try:
        service = ErrorAnalysisService(session)
        analysis = service.analyze_error_patterns(mission_id)
        return analysis
    except HTTPException:
        raise
    except Exception as e:
        raise handle_processing_error(
            operation="analyzing mission errors",
            error=e,
            resource=mission_id,
            user_id=str(current_user.id) if current_user else None
        )

@router.get("/dashboard/{mission_id}")
async def get_error_dashboard(
    mission_id: str,
    current_user: User = Depends(get_current_active_user),
    session: Session = Depends(get_db_session)
):
    """Get error dashboard summary for a mission"""
    try:
        service = ErrorAnalysisService(session)
        summary = service.get_dashboard_summary(mission_id)
        return summary
    except HTTPException:
        raise
    except Exception as e:
        raise handle_processing_error(
            operation="getting dashboard data",
            error=e,
            resource=mission_id,
            user_id=str(current_user.id) if current_user else None
        )

@router.get("/trends/{mission_id}")
async def get_error_trends(
    mission_id: str,
    days_back: int = Query(30, description="Number of days to look back"),
    current_user: User = Depends(get_current_active_user),
    session: Session = Depends(get_db_session)
):
    """Get error trend data for a mission"""
    try:
        service = ErrorAnalysisService(session)
        trends = service.get_error_trends(mission_id, days_back)
        return trends
    except HTTPException:
        raise
    except Exception as e:
        raise handle_processing_error(
            operation="getting error trends",
            error=e,
            resource=mission_id,
            user_id=str(current_user.id) if current_user else None
        )

@router.get("/plot/trends/{mission_id}")
async def get_error_trends_plot(
    mission_id: str,
    days_back: int = Query(30, description="Number of days to look back"),
    current_user: User = Depends(get_current_active_user),
    session: Session = Depends(get_db_session)
):
    """Get error trends plot as base64 encoded image"""
    try:
        service = ErrorAnalysisService(session)
        trends = service.get_error_trends(mission_id, days_back)
        
        # Create plot
        fig = plot_error_trends(trends, mission_id)
        
        # Convert to base64
        img_buffer = io.BytesIO()
        fig.savefig(img_buffer, format='png', dpi=150, bbox_inches='tight')
        img_buffer.seek(0)
        img_base64 = base64.b64encode(img_buffer.getvalue()).decode()
        
        plt.close(fig)  # Clean up
        
        return {"image": f"data:image/png;base64,{img_base64}"}
    except HTTPException:
        raise
    except Exception as e:
        raise handle_processing_error(
            operation="generating trends plot",
            error=e,
            resource=mission_id,
            user_id=str(current_user.id) if current_user else None
        )

@router.get("/plot/heatmap/{mission_id}")
async def get_error_heatmap_plot(
    mission_id: str,
    days_back: int = Query(30, description="Number of days to look back"),
    current_user: User = Depends(get_current_active_user),
    session: Session = Depends(get_db_session)
):
    """Get error heatmap plot as base64 encoded image"""
    try:
        service = ErrorAnalysisService(session)
        trends = service.get_error_trends(mission_id, days_back)
        
        # Create heatmap
        fig = plot_error_heatmap(trends, mission_id)
        
        # Convert to base64
        img_buffer = io.BytesIO()
        fig.savefig(img_buffer, format='png', dpi=150, bbox_inches='tight')
        img_buffer.seek(0)
        img_base64 = base64.b64encode(img_buffer.getvalue()).decode()
        
        plt.close(fig)  # Clean up
        
        return {"image": f"data:image/png;base64,{img_base64}"}
    except HTTPException:
        raise
    except Exception as e:
        raise handle_processing_error(
            operation="generating heatmap plot",
            error=e,
            resource=mission_id,
            user_id=str(current_user.id) if current_user else None
        )

@router.get("/plot/dashboard/{mission_id}")
async def get_error_dashboard_plot(
    mission_id: str,
    current_user: User = Depends(get_current_active_user),
    session: Session = Depends(get_db_session)
):
    """Get error dashboard plot as base64 encoded image"""
    try:
        service = ErrorAnalysisService(session)
        summary = service.get_dashboard_summary(mission_id)
        
        # Create dashboard plot
        fig = plot_error_summary_dashboard(summary, mission_id)
        
        # Convert to base64
        img_buffer = io.BytesIO()
        fig.savefig(img_buffer, format='png', dpi=150, bbox_inches='tight')
        img_buffer.seek(0)
        img_base64 = base64.b64encode(img_buffer.getvalue()).decode()
        
        plt.close(fig)  # Clean up
        
        return {"image": f"data:image/png;base64,{img_base64}"}
    except HTTPException:
        raise
    except Exception as e:
        raise handle_processing_error(
            operation="generating dashboard plot",
            error=e,
            resource=mission_id,
            user_id=str(current_user.id) if current_user else None
        )

@router.get("/plot/timeline/{mission_id}")
async def get_error_timeline_plot(
    mission_id: str,
    days_back: int = Query(30, description="Number of days to look back"),
    current_user: User = Depends(get_current_active_user),
    session: Session = Depends(get_db_session)
):
    """Get error timeline plot as base64 encoded image"""
    try:
        service = ErrorAnalysisService(session)
        trends = service.get_error_trends(mission_id, days_back)
        
        # Create timeline plot - convert trends to DataFrame format
        import pandas as pd
        timeline_data = pd.DataFrame([{
            'timestamp': pd.to_datetime(trend.time_period),
            'self_corrected': trend.self_correction_rate > 50  # Convert rate to boolean
        } for trend in trends])
        fig = plot_error_timeline(timeline_data, mission_id)
        
        # Convert to base64
        img_buffer = io.BytesIO()
        fig.savefig(img_buffer, format='png', dpi=150, bbox_inches='tight')
        img_buffer.seek(0)
        img_base64 = base64.b64encode(img_buffer.getvalue()).decode()
        
        plt.close(fig)  # Clean up
        
        return {"image": f"data:image/png;base64,{img_base64}"}
    except HTTPException:
        raise
    except Exception as e:
        raise handle_processing_error(
            operation="generating timeline plot",
            error=e,
            resource=mission_id,
            user_id=str(current_user.id) if current_user else None
        )

# HTML endpoints for web interface
@router.get("/dashboard.html", response_class=HTMLResponse)
async def get_error_dashboard_page(
    current_user: User = Depends(get_current_active_user)
):
    """Error analysis dashboard page"""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Error Analysis Dashboard</title>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
        <style>
            .error-card { margin-bottom: 20px; }
            .plot-container { text-align: center; margin: 20px 0; }
            .plot-container img { max-width: 100%; height: auto; }
        </style>
    </head>
    <body>
        <div class="container-fluid">
            <h1>Error Analysis Dashboard</h1>
            <div class="row">
                <div class="col-md-6">
                    <div class="card error-card">
                        <div class="card-header">
                            <h5>Mission Selection</h5>
                        </div>
                        <div class="card-body">
                            <div class="mb-3">
                                <label for="missionSelect" class="form-label">Select Mission:</label>
                                <select class="form-select" id="missionSelect">
                                    <option value="m209">M209</option>
                                    <option value="m211">M211</option>
                                </select>
                            </div>
                            <button class="btn btn-primary" onclick="loadErrorAnalysis()">Load Analysis</button>
                        </div>
                    </div>
                </div>
                <div class="col-md-6">
                    <div class="card error-card">
                        <div class="card-header">
                            <h5>Error Classification Test</h5>
                        </div>
                        <div class="card-body">
                            <div class="mb-3">
                                <label for="errorMessage" class="form-label">Test Error Message:</label>
                                <input type="text" class="form-control" id="errorMessage" 
                                       placeholder="Enter error message to classify">
                            </div>
                            <button class="btn btn-secondary" onclick="classifyError()">Classify</button>
                            <div id="classificationResult" class="mt-3"></div>
                        </div>
                    </div>
                </div>
            </div>
            
            <div id="errorAnalysis" style="display: none;">
                <div class="row">
                    <div class="col-12">
                        <div class="card error-card">
                            <div class="card-header">
                                <h5>Error Trends</h5>
                            </div>
                            <div class="card-body">
                                <div class="plot-container" id="trendsPlot"></div>
                            </div>
                        </div>
                    </div>
                </div>
                
                <div class="row">
                    <div class="col-md-6">
                        <div class="card error-card">
                            <div class="card-header">
                                <h5>Error Heatmap</h5>
                            </div>
                            <div class="card-body">
                                <div class="plot-container" id="heatmapPlot"></div>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-6">
                        <div class="card error-card">
                            <div class="card-header">
                                <h5>Error Timeline</h5>
                            </div>
                            <div class="card-body">
                                <div class="plot-container" id="timelinePlot"></div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        
        <script>
            async function loadErrorAnalysis() {
                const missionId = document.getElementById('missionSelect').value;
                
                try {
                    // Load trends plot
                    const trendsResponse = await fetch(`/api/errors/plot/trends/${missionId}`);
                    const trendsData = await trendsResponse.json();
                    document.getElementById('trendsPlot').innerHTML = 
                        `<img src="${trendsData.image}" alt="Error Trends">`;
                    
                    // Load heatmap plot
                    const heatmapResponse = await fetch(`/api/errors/plot/heatmap/${missionId}`);
                    const heatmapData = await heatmapResponse.json();
                    document.getElementById('heatmapPlot').innerHTML = 
                        `<img src="${heatmapData.image}" alt="Error Heatmap">`;
                    
                    // Load timeline plot
                    const timelineResponse = await fetch(`/api/errors/plot/timeline/${missionId}`);
                    const timelineData = await timelineResponse.json();
                    document.getElementById('timelinePlot').innerHTML = 
                        `<img src="${timelineData.image}" alt="Error Timeline">`;
                    
                    document.getElementById('errorAnalysis').style.display = 'block';
                } catch (error) {
                    alert('Error loading analysis: ' + error.message);
                }
            }
            
            async function classifyError() {
                const message = document.getElementById('errorMessage').value;
                if (!message.trim()) {
                    alert('Please enter an error message');
                    return;
                }
                
                try {
                    const response = await fetch(`/api/errors/classify?error_message=${encodeURIComponent(message)}`);
                    const result = await response.json();
                    
                    document.getElementById('classificationResult').innerHTML = `
                        <div class="alert alert-info">
                            <strong>Category:</strong> ${result.category}<br>
                            <strong>Confidence:</strong> ${(result.confidence * 100).toFixed(1)}%<br>
                            <strong>Description:</strong> ${result.description}
                        </div>
                    `;
                } catch (error) {
                    alert('Error classifying message: ' + error.message);
                }
            }
        </script>
    </body>
    </html>
    """


@router.get("/csv/recent")
async def download_recent_errors_csv(
    mission: str = Query(..., description="Mission name"),
    hours: int = Query(24, description="Number of hours to look back"),
    current_user: User = Depends(get_current_active_user)
):
    """Download recent errors (last 24 hours) as CSV"""
    try:
        # Use data service (no circular dependency)
        from ..core.summaries import get_recent_errors
        from ..services.error_classification_service import classify_error_message
        
        data_service = get_data_service()
        # Load and validate error data using consolidated helper
        errors_df, _, _ = await data_service.load_and_validate(
            report_type="errors",
            mission_id=mission,
            error_message="No error data found for this mission",
            current_user=current_user
        )
        
        # Get recent errors using the same logic as the dashboard
        recent_errors = get_recent_errors(errors_df, max_age_hours=hours)
        
        # Create CSV
        output = io.StringIO()
        csv_writer = csv.writer(output)
        
        # Write header
        csv_writer.writerow([
            "Timestamp", "Vehicle Name", "Category", "Error Message", 
            "Self Corrected", "Confidence", "Category Description"
        ])
        
        # Write data rows using the same data as the dashboard
        for error in recent_errors:
            # Classify the error using the same logic as the dashboard
            if error.get('ErrorMessage'):
                category, confidence, description = classify_error_message(error['ErrorMessage'])
                category_name = category.value
                confidence_pct = confidence
                category_desc = description
            else:
                category_name = 'unknown'
                confidence_pct = 0.0
                category_desc = 'Unknown error type'
            
            csv_writer.writerow([
                error.get('Timestamp', '').strftime('%Y-%m-%d %H:%M:%S') if error.get('Timestamp') else '',
                error.get('VehicleName', ''),
                category_name,
                error.get('ErrorMessage', ''),
                'Yes' if error.get('SelfCorrected') else 'No',
                f"{confidence_pct:.1%}",
                category_desc
            ])
        
        output.seek(0)
        content = output.getvalue()
        filename = f"recent_errors_{mission}_{hours}h_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        return StreamingResponse(
            io.BytesIO(content.encode("utf-8")), 
            media_type="text/csv", 
            headers={"Content-Disposition": f"attachment; filename=\"{filename}\""}
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise handle_processing_error(
            operation="generating recent errors CSV",
            error=e,
            resource=mission,
            user_id=str(current_user.id) if current_user else None
        )


@router.get("/csv/all")
async def download_all_errors_csv(
    mission: str = Query(..., description="Mission name"),
    current_user: User = Depends(get_current_active_user)
):
    """Download all mission errors as CSV"""
    try:
        # Use data service (no circular dependency)
        from ..services.error_classification_service import classify_error_message
        
        data_service = get_data_service()
        # Load and validate error data using consolidated helper
        all_errors_df, _ = await data_service.load_and_validate(
            report_type="errors",
            mission_id=mission,
            error_message="No error data found for this mission",
            current_user=current_user
        )
        
        # Create CSV
        output = io.StringIO()
        csv_writer = csv.writer(output)
        
        # Write header
        csv_writer.writerow([
            "Timestamp", "Vehicle Name", "Category", "Error Message", 
            "Self Corrected", "Confidence", "Category Description"
        ])
        
        # Process all errors using the same logic as the dashboard
        for _, row in all_errors_df.iterrows():
            # Convert timestamp to datetime if it's a string (same logic as dashboard)
            timestamp = row.get('Timestamp') or row.get('timeStamp')
            if isinstance(timestamp, str):
                try:
                    timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                except (ValueError, AttributeError):
                    timestamp = None
            
            # Classify the error using the same logic as the dashboard
            error_message = row.get('ErrorMessage') or row.get('error_Message')
            if error_message:
                category, confidence, description = classify_error_message(error_message)
                category_name = category.value
                confidence_pct = confidence
                category_desc = description
            else:
                category_name = 'unknown'
                confidence_pct = 0.0
                category_desc = 'Unknown error type'
            
            csv_writer.writerow([
                timestamp.strftime('%Y-%m-%d %H:%M:%S') if timestamp else '',
                row.get('VehicleName') or row.get('vehicleName', ''),
                category_name,
                error_message or '',
                'Yes' if row.get('SelfCorrected') or row.get('selfCorrected') else 'No',
                f"{confidence_pct:.1%}",
                category_desc
            ])
        
        output.seek(0)
        content = output.getvalue()
        filename = f"all_errors_{mission}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        return StreamingResponse(
            io.BytesIO(content.encode("utf-8")), 
            media_type="text/csv", 
            headers={"Content-Disposition": f"attachment; filename=\"{filename}\""}
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise handle_processing_error(
            operation="generating all errors CSV",
            error=e,
            resource=mission,
            user_id=str(current_user.id) if current_user else None
        )
