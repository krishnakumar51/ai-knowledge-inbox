class AppError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class ServiceUnavailableError(AppError):
    status_code = 503
    code = "service_unavailable"


class ProviderError(AppError):
    status_code = 502
    code = "provider_error"


class InvalidSourceError(AppError):
    status_code = 422
    code = "invalid_source"


class UpstreamError(AppError):
    status_code = 502
    code = "upstream_error"
