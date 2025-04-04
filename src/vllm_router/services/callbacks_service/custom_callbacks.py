from abc import abstractmethod

from fastapi import Request, Response


class CustomCallbackHandler:
    """
    Abstract class

    Callbacks can be injected at multiple points within the request lifecycle.
    This can be used to validate the request or log the response.
    """

    @abstractmethod
    def pre_request(
        self, request: Request, request_body: bytes, request_json: any
    ) -> Response | None:
        """
        Receives the request object before it gets proxied.
        This can be used to validate the request or raise HTTP responses.

        Args:
            request: The original request
            request_body: The request body as a byte array.
            request_json: The request body as a JSON object.

        Returns:
            Either None or a Response Object which will end the request.
        """
        return None

    @abstractmethod
    def post_request(self, request: Request, response_content: bytes) -> None:
        """
        Is executed as a background task, receives the request object and the complete response_content.
        This can be used to log the response or further process it.

        Args:
            request: The original request
            response_content: The complete response content after the request has been completed as a byte array.
        """
        pass
