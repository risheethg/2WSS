from fastapi.responses import JSONResponse
from typing import Any, Optional, Dict

class Response:
    @staticmethod
    def success(data: Any = None, message: str = "Request successful", status_code: int = 200) -> JSONResponse:
        """
        Creates a standardized success response using JSONResponse.
        """
        return JSONResponse(
            status_code=status_code,
            content={
                "status": "success",
                "message": message,
                "data": data,
                "status_code": status_code
            }
        )

    @staticmethod
    def failure(message: str, status_code: int = 400, error_details: Optional[Dict] = None) -> JSONResponse:
        """
        Creates a standardized failure response using JSONResponse.
        """
        return JSONResponse(
            status_code=status_code,
            content={
                "status": "failure",
                "message": message,
                "error_details": error_details,
                "status_code": status_code
            }
        )

response_handler = Response()