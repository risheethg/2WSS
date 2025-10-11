"""
Retry utility with exponential backoff for handling transient failures.
"""

import time
import random
from typing import Callable, Any, Optional, Set
from functools import wraps
from app.core.config import settings
from app.core.logger import worker_logger as logger
import stripe


class RetryableError(Exception):
    """Exception that indicates an operation should be retried"""
    pass


class NonRetryableError(Exception):
    """Exception that indicates an operation should NOT be retried"""
    pass


def is_retryable_stripe_error(error: Exception) -> bool:
    """Determine if a Stripe error should be retried"""
    if isinstance(error, stripe.error.RateLimitError):
        return True
    elif isinstance(error, stripe.error.APIConnectionError):
        return True
    elif isinstance(error, stripe.error.APIError):
        return True
    elif isinstance(error, stripe.error.InvalidRequestError):
        # These are usually client errors that won't succeed on retry
        return False
    elif isinstance(error, stripe.error.AuthenticationError):
        return False
    elif isinstance(error, stripe.error.PermissionError):
        return False
    else:
        # For unknown errors, err on the side of retrying
        return True


def calculate_backoff_delay(attempt: int, base_delay: int = None, max_delay: int = None) -> float:
    """Calculate exponential backoff delay with jitter"""
    base_delay = base_delay or settings.INITIAL_RETRY_DELAY
    max_delay = max_delay or settings.MAX_RETRY_DELAY
    
    # Exponential backoff: base_delay * (2 ^ attempt)
    delay = base_delay * (2 ** attempt)
    
    # Cap at max_delay
    delay = min(delay, max_delay)
    
    # Add jitter (±25% randomness) to prevent thundering herd
    jitter = delay * 0.25 * random.uniform(-1, 1)
    final_delay = delay + jitter
    
    return max(0, final_delay)


def retry_with_backoff(
    max_attempts: int = None,
    retryable_errors: Set[type] = None,
    backoff_base: int = None,
    backoff_max: int = None
):
    """Decorator for retrying functions with exponential backoff"""
    
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            max_retries = max_attempts or settings.MAX_RETRY_ATTEMPTS
            attempt = 0
            last_exception = None
            
            while attempt < max_retries:
                try:
                    return func(*args, **kwargs)
                    
                except Exception as e:
                    last_exception = e
                    attempt += 1
                    
                    # Determine if we should retry
                    should_retry = False
                    
                    if retryable_errors and type(e) in retryable_errors:
                        should_retry = True
                    elif hasattr(e, '__module__') and 'stripe' in e.__module__:
                        should_retry = is_retryable_stripe_error(e)
                    elif isinstance(e, (RetryableError,)):
                        should_retry = True
                    elif isinstance(e, (NonRetryableError,)):
                        should_retry = False
                    else:
                        # Default: retry for most exceptions
                        should_retry = True
                    
                    if not should_retry or attempt >= max_retries:
                        logger.error(f"Function {func.__name__} failed permanently after {attempt} attempts: {e}")
                        raise e
                    
                    # Calculate backoff delay
                    delay = calculate_backoff_delay(
                        attempt - 1,  # 0-indexed for calculation
                        backoff_base,
                        backoff_max
                    )
                    
                    logger.warning(f"Function {func.__name__} failed (attempt {attempt}/{max_retries}): {e}. Retrying in {delay:.2f}s")
                    time.sleep(delay)
            
            # This should never be reached, but just in case
            raise last_exception
            
        return wrapper
    return decorator


class EventProcessor:
    """Handles event processing with retry logic"""
    
    @retry_with_backoff(max_attempts=settings.MAX_RETRY_ATTEMPTS)
    def process_stripe_event(self, integration, event_type: str, customer_data: dict, db):
        """Process Stripe event with automatic retry"""
        try:
            if event_type == "customer_created":
                result = integration.create_customer(customer_data, db)
            elif event_type == "customer_updated":
                result = integration.update_customer(customer_data, db)
            elif event_type == "customer_deleted":
                result = integration.delete_customer(customer_data, db)
            else:
                raise NonRetryableError(f"Unknown event type: {event_type}")
            
            if not result:
                raise RetryableError(f"Integration returned failure for {event_type}")
                
            return result
            
        except stripe.error.StripeError as e:
            # Let the retry decorator handle Stripe errors
            raise e
        except Exception as e:
            # Wrap unknown exceptions
            logger.error(f"Unexpected error in event processing: {e}")
            raise RetryableError(f"Unexpected error: {e}")


# Global processor instance  
event_processor = EventProcessor()