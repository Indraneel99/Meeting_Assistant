from fastapi import Request

from meeting_assistant.container import Container


def get_container(request: Request) -> Container:
    return request.app.state.container
