"""
Database Health Monitoring Service

This module provides comprehensive database monitoring including:
- Connection pool health monitoring
- Performance metrics tracking
- Deadlock and constraint violation statistics
- Connection timeout monitoring
- Query performance analysis
- Proactive health alerts
"""

import time
import logging
import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum

from sqlalchemy import text, inspect
from sqlalchemy.orm import Session
from sqlalchemy.pool import Pool

from .database import engine, DatabaseHealthChecker
from .deadlock_detector import deadlock_detector, DeadlockSeverity
from .constraint_handler import constraint_handler
from .config import settings

logger = logging.getLogger(__name__)

class HealthStatus(Enum):
    """Overall health status levels."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    CRITICAL = "critical"

@dataclass
class DatabaseMetrics:
    """Database performance and health metrics."""
    timestamp: datetime
    connection_pool_size: int
    connections_checked_out: int
    connections_checked_in: int
    connections_overflow: int
    connections_invalid: int
    active_connections: int
    
    # Performance metrics
    avg_query_time: float
    slow_query_count: int
    failed_query_count: int
    
    # Error metrics
    deadlock_count_24h: int
    constraint_violation_count_24h: int
    connection_timeout_count_24h: int
    
    # Health indicators
    overall_health: HealthStatus
    pool_utilization: float  # Percentage of pool in use
    error_rate: float  # Errors per hour
    
    def to_dict(self) -> Dict:
        """Convert metrics to dictionary."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "connection_pool": {
                "size": self.connection_pool_size,
                "checked_out": self.connections_checked_out,
                "checked_in": self.connections_checked_in,
                "overflow": self.connections_overflow,
                "invalid": self.connections_invalid,
                "active": self.active_connections,
                "utilization_percent": self.pool_utilization
            },
            "performance": {
                "avg_query_time_ms": self.avg_query_time * 1000,
                "slow_query_count": self.slow_query_count,
                "failed_query_count": self.failed_query_count
            },
            "errors_24h": {
                "deadlocks": self.deadlock_count_24h,
                "constraint_violations": self.constraint_violation_count_24h,
                "connection_timeouts": self.connection_timeout_count_24h,
                "error_rate_per_hour": self.error_rate
            },
            "health": {
                "status": self.overall_health.value,
                "assessment_time": self.timestamp.isoformat()
            }
        }

class QueryPerformanceTracker:
    """Track query performance metrics."""
    
    def __init__(self, max_samples: int = 1000):
        self.query_times: List[float] = []
        self.slow_queries: List[Dict] = []
        self.failed_queries: List[Dict] = []
        self.max_samples = max_samples
        self.slow_query_threshold = 1.0  # seconds
    
    def record_query(self, duration: float, query: str, success: bool = True):
        """Record query execution."""
        self.query_times.append(duration)
        
        # Maintain sample size
        if len(self.query_times) > self.max_samples:
            self.query_times.pop(0)
        
        # Track slow queries
        if duration > self.slow_query_threshold:
            self.slow_queries.append({
                "duration": duration,
                "query": query[:200],  # Truncate for storage
                "timestamp": datetime.utcnow()
            })
            
            if len(self.slow_queries) > 100:  # Keep last 100
                self.slow_queries.pop(0)
        
        # Track failed queries
        if not success:
            self.failed_queries.append({
                "query": query[:200],
                "timestamp": datetime.utcnow()
            })
            
            if len(self.failed_queries) > 100:  # Keep last 100
                self.failed_queries.pop(0)
    
    def get_metrics(self) -> Dict:
        """Get performance metrics."""
        if not self.query_times:
            return {
                "avg_duration": 0.0,
                "slow_query_count": 0,
                "failed_query_count": 0,
                "total_queries": 0
            }
        
        return {
            "avg_duration": sum(self.query_times) / len(self.query_times),
            "slow_query_count": len(self.slow_queries),
            "failed_query_count": len(self.failed_queries),
            "total_queries": len(self.query_times),
            "min_duration": min(self.query_times),
            "max_duration": max(self.query_times)
        }

class DatabaseMonitoringService:
    """
    Comprehensive database monitoring service.
    """
    
    def __init__(self):
        self.query_tracker = QueryPerformanceTracker()
        self.connection_timeout_events: List[datetime] = []
        self.health_check_interval = 60  # seconds
        self.last_health_check: Optional[datetime] = None
        self.monitoring_active = False
    
    def get_connection_pool_metrics(self) -> Dict[str, int]:
        """Get current connection pool metrics."""
        pool = engine.pool
        
        return {
            "size": pool.size(),
            "checked_out": pool.checkedout(),
            "overflow": pool.overflow(),
            "invalid": pool.invalid(),
            "checked_in": pool.checkedin()
        }
    
    def assess_pool_health(self, pool_metrics: Dict[str, int]) -> HealthStatus:
        """Assess connection pool health."""
        utilization = pool_metrics["checked_out"] / max(pool_metrics["size"], 1)
        
        # Check for critical conditions
        if pool_metrics["invalid"] > 0 or utilization > 0.95:
            return HealthStatus.CRITICAL
        elif utilization > 0.8 or pool_metrics["overflow"] > 10:
            return HealthStatus.DEGRADED
        elif utilization > 0.6:
            return HealthStatus.HEALTHY
        else:
            return HealthStatus.HEALTHY
    
    def record_connection_timeout(self):
        """Record a connection timeout event."""
        self.connection_timeout_events.append(datetime.utcnow())
        
        # Keep only last 24 hours
        cutoff = datetime.utcnow() - timedelta(hours=24)
        self.connection_timeout_events = [
            event for event in self.connection_timeout_events 
            if event > cutoff
        ]
    
    def get_database_metrics(self) -> DatabaseMetrics:
        """Get comprehensive database metrics."""
        # Connection pool metrics
        pool_metrics = self.get_connection_pool_metrics()
        pool_health = self.assess_pool_health(pool_metrics)
        
        # Performance metrics
        perf_metrics = self.query_tracker.get_metrics()
        
        # Deadlock statistics
        deadlock_stats = deadlock_detector.get_deadlock_statistics(hours=24)
        
        # Connection timeouts in last 24 hours
        timeout_count = len(self.connection_timeout_events)
        
        # Calculate overall health
        overall_health = self._assess_overall_health(
            pool_health,
            deadlock_stats,
            perf_metrics,
            timeout_count
        )
        
        # Calculate utilization
        pool_utilization = (
            pool_metrics["checked_out"] / max(pool_metrics["size"], 1) * 100
        )
        
        # Calculate error rate (errors per hour)
        total_errors = (
            deadlock_stats["total_deadlocks"] +
            timeout_count +
            perf_metrics["failed_query_count"]
        )
        error_rate = total_errors / 24.0  # per hour over 24 hours
        
        return DatabaseMetrics(
            timestamp=datetime.utcnow(),
            connection_pool_size=pool_metrics["size"],
            connections_checked_out=pool_metrics["checked_out"],
            connections_checked_in=pool_metrics["checked_in"],
            connections_overflow=pool_metrics["overflow"],
            connections_invalid=pool_metrics["invalid"],
            active_connections=pool_metrics["checked_out"],
            avg_query_time=perf_metrics["avg_duration"],
            slow_query_count=perf_metrics["slow_query_count"],
            failed_query_count=perf_metrics["failed_query_count"],
            deadlock_count_24h=deadlock_stats["total_deadlocks"],
            constraint_violation_count_24h=0,  # Would need implementation
            connection_timeout_count_24h=timeout_count,
            overall_health=overall_health,
            pool_utilization=pool_utilization,
            error_rate=error_rate
        )
    
    def _assess_overall_health(
        self, 
        pool_health: HealthStatus,
        deadlock_stats: Dict,
        perf_metrics: Dict,
        timeout_count: int
    ) -> HealthStatus:
        """Assess overall database health."""
        
        # Start with pool health as baseline
        health_scores = {
            HealthStatus.HEALTHY: 0,
            HealthStatus.DEGRADED: 1,
            HealthStatus.UNHEALTHY: 2,
            HealthStatus.CRITICAL: 3
        }
        
        current_score = health_scores[pool_health]
        
        # Factor in deadlock severity
        deadlock_severity = DeadlockSeverity(deadlock_stats["severity"])
        if deadlock_severity == DeadlockSeverity.CRITICAL:
            current_score = max(current_score, 3)
        elif deadlock_severity == DeadlockSeverity.HIGH:
            current_score = max(current_score, 2)
        elif deadlock_severity == DeadlockSeverity.MEDIUM:
            current_score = max(current_score, 1)
        
        # Factor in connection timeouts
        if timeout_count > 50:  # More than 50 timeouts in 24h
            current_score = max(current_score, 2)
        elif timeout_count > 20:
            current_score = max(current_score, 1)
        
        # Factor in query performance
        if perf_metrics["avg_duration"] > 5.0:  # Very slow queries
            current_score = max(current_score, 2)
        elif perf_metrics["avg_duration"] > 2.0:  # Slow queries
            current_score = max(current_score, 1)
        
        # Convert back to health status
        for status, score in health_scores.items():
            if score == current_score:
                return status
        
        return HealthStatus.HEALTHY
    
    def run_database_diagnostics(self, db: Session) -> Dict[str, Any]:
        """
        Run comprehensive database diagnostics.
        
        Args:
            db: Database session
            
        Returns:
            Dict: Diagnostic results
        """
        diagnostics = {
            "timestamp": datetime.utcnow().isoformat(),
            "tests": []
        }
        
        # Test 1: Basic connectivity
        try:
            result = db.execute(text("SELECT 1")).fetchone()
            diagnostics["tests"].append({
                "test": "basic_connectivity",
                "status": "pass",
                "message": "Database connection successful"
            })
        except Exception as e:
            diagnostics["tests"].append({
                "test": "basic_connectivity", 
                "status": "fail",
                "message": f"Database connection failed: {e}"
            })
        
        # Test 2: Query performance
        try:
            start_time = time.time()
            db.execute(text("SELECT COUNT(*) FROM customers")).fetchone()
            duration = time.time() - start_time
            
            status = "pass" if duration < 1.0 else "warn" if duration < 5.0 else "fail"
            diagnostics["tests"].append({
                "test": "query_performance",
                "status": status,
                "message": f"Customer count query took {duration:.3f}s",
                "duration": duration
            })
        except Exception as e:
            diagnostics["tests"].append({
                "test": "query_performance",
                "status": "fail", 
                "message": f"Query performance test failed: {e}"
            })
        
        # Test 3: Transaction handling
        try:
            with db.begin():
                db.execute(text("SELECT 1"))
                # Rollback to test transaction handling
                db.rollback()
            
            diagnostics["tests"].append({
                "test": "transaction_handling",
                "status": "pass",
                "message": "Transaction rollback successful"
            })
        except Exception as e:
            diagnostics["tests"].append({
                "test": "transaction_handling",
                "status": "fail",
                "message": f"Transaction test failed: {e}"
            })
        
        # Test 4: Pool status
        pool_metrics = self.get_connection_pool_metrics()
        pool_health = self.assess_pool_health(pool_metrics)
        
        diagnostics["tests"].append({
            "test": "connection_pool",
            "status": "pass" if pool_health == HealthStatus.HEALTHY else "warn",
            "message": f"Pool health: {pool_health.value}",
            "metrics": pool_metrics
        })
        
        # Overall diagnostic status
        failed_tests = sum(1 for test in diagnostics["tests"] if test["status"] == "fail")
        warning_tests = sum(1 for test in diagnostics["tests"] if test["status"] == "warn")
        
        if failed_tests > 0:
            diagnostics["overall_status"] = "critical"
        elif warning_tests > 0:
            diagnostics["overall_status"] = "degraded"
        else:
            diagnostics["overall_status"] = "healthy"
        
        return diagnostics
    
    def get_monitoring_dashboard(self) -> Dict[str, Any]:
        """
        Get comprehensive monitoring dashboard data.
        
        Returns:
            Dict: Dashboard data for monitoring interfaces
        """
        metrics = self.get_database_metrics()
        deadlock_stats = deadlock_detector.get_deadlock_statistics(hours=24)
        
        return {
            "summary": {
                "status": metrics.overall_health.value,
                "timestamp": metrics.timestamp.isoformat(),
                "uptime_check": "operational"
            },
            "connection_pool": {
                "total_connections": metrics.connection_pool_size,
                "active_connections": metrics.connections_checked_out,
                "utilization_percent": metrics.pool_utilization,
                "overflow_connections": metrics.connections_overflow,
                "invalid_connections": metrics.connections_invalid
            },
            "performance": {
                "avg_query_time_ms": metrics.avg_query_time * 1000,
                "slow_queries_24h": metrics.slow_query_count,
                "failed_queries_24h": metrics.failed_query_count,
                "error_rate_per_hour": metrics.error_rate
            },
            "reliability": {
                "deadlocks_24h": metrics.deadlock_count_24h,
                "deadlock_severity": deadlock_stats["severity"],
                "connection_timeouts_24h": metrics.connection_timeout_count_24h,
                "recovery_success_rate": deadlock_stats.get("recovery_success_rate", 1.0)
            },
            "recommendations": self._get_health_recommendations(metrics, deadlock_stats),
            "alerts": self._get_active_alerts(metrics, deadlock_stats)
        }
    
    def _get_health_recommendations(self, metrics: DatabaseMetrics, deadlock_stats: Dict) -> List[str]:
        """Get health improvement recommendations."""
        recommendations = []
        
        if metrics.pool_utilization > 80:
            recommendations.append("Consider increasing connection pool size")
        
        if metrics.avg_query_time > 1.0:
            recommendations.append("Review slow queries and add database indexes")
        
        if deadlock_stats["severity"] in ["high", "critical"]:
            recommendations.extend(deadlock_detector.get_deadlock_prevention_recommendations()[:3])
        
        if metrics.connection_timeout_count_24h > 10:
            recommendations.append("Investigate network connectivity or increase connection timeout")
        
        if not recommendations:
            recommendations.append("Database performance is optimal")
        
        return recommendations
    
    def _get_active_alerts(self, metrics: DatabaseMetrics, deadlock_stats: Dict) -> List[Dict]:
        """Get active alerts that need attention."""
        alerts = []
        
        if metrics.overall_health == HealthStatus.CRITICAL:
            alerts.append({
                "level": "critical",
                "message": "Database health is critical - immediate attention required",
                "component": "overall_health"
            })
        
        if metrics.pool_utilization > 95:
            alerts.append({
                "level": "critical",
                "message": f"Connection pool utilization at {metrics.pool_utilization:.1f}%",
                "component": "connection_pool"
            })
        
        if deadlock_stats["severity"] == "critical":
            alerts.append({
                "level": "critical", 
                "message": f"Critical deadlock frequency: {deadlock_stats['deadlock_rate']:.1f}/hour",
                "component": "deadlocks"
            })
        
        if metrics.connection_timeout_count_24h > 50:
            alerts.append({
                "level": "warning",
                "message": f"{metrics.connection_timeout_count_24h} connection timeouts in 24h",
                "component": "connectivity"
            })
        
        return alerts

# Global monitoring service instance
db_monitor = DatabaseMonitoringService()