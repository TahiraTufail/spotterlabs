class PlanError(Exception):
    code = "plan_error"
    status = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class InvalidLocation(PlanError):
    code = "invalid_location"
    status = 400


class OutsideUsa(PlanError):
    code = "outside_usa"
    status = 422


class NoRoute(PlanError):
    code = "no_route"
    status = 422


class NoFuelInRange(PlanError):
    code = "no_fuel_in_range"
    status = 422


class UpstreamError(PlanError):
    code = "routing_provider_error"
    status = 502
