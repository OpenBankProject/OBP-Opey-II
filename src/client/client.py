import json
import os
from collections.abc import AsyncGenerator, Generator
from typing import Any

import httpx

from schema import ChatMessage, Feedback, StreamInput, UserInput, ToolCallApproval
from typing import Union
from dotenv import load_dotenv

load_dotenv()

class AgentClient:
    """Client for interacting with the agent service."""

    def __init__(self, base_url: str = "http://localhost:8000", timeout: float | None = None) -> None:
        """
        Initialize the client.

        Args:
            base_url (str): The base URL of the agent service.
        """
        self.base_url = base_url
        self.auth_secret = os.getenv("AUTH_SECRET")
        self.consent_jwt = os.getenv("CONSENT_JWT")
        self.timeout = timeout
        # Create clients for session management
        self._client = httpx.Client(timeout=timeout)
        self._async_client = httpx.AsyncClient(timeout=timeout)
        self._session_created = False
        self.session_id = None  # Store session ID
        self.session_cookie = None  # Store session cookie for manual inclusion

    @property
    def _headers(self) -> dict[str, str]:
        headers = {}
        if self.auth_secret:
            headers["Authorization"] = f"Bearer {self.auth_secret}"
        if self.consent_jwt:
            headers["Consent-JWT"] = self.consent_jwt
        return headers

    def _ensure_session(self) -> None:
        """Ensure a session exists by calling /create-session if needed."""
        if not self._session_created:
            print(f"Creating session at {self.base_url}/create-session")
            response = self._client.post(f"{self.base_url}/create-session", headers=self._headers)
            print(f"Session creation response: {response.status_code}")
            print(f"Session cookies received: {response.cookies}")
            if response.status_code == 200:
                self._session_created = True
                # Store session cookie value for manual header inclusion
                for name, value in response.cookies.items():
                    if name == "session":
                        self.session_cookie = f"{name}={value}"
                        print(f"Stored session cookie: {self.session_cookie}")
                # Try to extract session_id from response data if available
                try:
                    data = response.json()
                    self.session_id = data.get("session_id")
                    if self.session_id:
                        print(f"Session ID extracted: {self.session_id}")
                except:
                    # If no JSON response or no session_id field, that's okay
                    print("No session_id in response data, using cookie-based session")
                print("Session created successfully")
            else:
                raise Exception(f"Failed to create session: {response.status_code} - {response.text}")

    async def _aensure_session(self) -> None:
        """Ensure a session exists by calling /create-session if needed (async)."""
        if not self._session_created:
            print(f"Creating async session at {self.base_url}/create-session")
            response = await self._async_client.post(f"{self.base_url}/create-session", headers=self._headers)
            print(f"Async session creation response: {response.status_code}")
            print(f"Async session cookies received: {response.cookies}")
            if response.status_code == 200:
                self._session_created = True
                # Store session cookie value for manual header inclusion
                for name, value in response.cookies.items():
                    if name == "session":
                        self.session_cookie = f"{name}={value}"
                        print(f"Stored session cookie: {self.session_cookie}")
                # Try to extract session_id from response data if available
                try:
                    data = response.json()
                    self.session_id = data.get("session_id")
                    if self.session_id:
                        print(f"Session ID extracted: {self.session_id}")
                except:
                    # If no JSON response or no session_id field, that's okay
                    print("No session_id in response data, using cookie-based session")
                print("Async session created successfully")
            else:
                raise Exception(f"Failed to create session: {response.status_code} - {response.text}")

    def __del__(self):
        """Clean up clients on deletion."""
        try:
            self._client.close()
        except:
            pass
        try:
            # Async client cleanup in __del__ is problematic since we can't await
            # httpx will handle cleanup automatically when the object is garbage collected
            # Just set the reference to None to help with cleanup
            if hasattr(self, '_async_client'):
                self._async_client = None
        except:
            pass

    async def ainvoke(
        self, message: str, model: str | None = None, thread_id: str | None = None
    ) -> ChatMessage:
        """
        Invoke the agent asynchronously. Only the final message is returned.

        Args:
            message (str): The message to send to the agent
            model (str, optional): LLM model to use for the agent
            thread_id (str, optional): Thread ID for continuing a conversation

        Returns:
            AnyMessage: The response from the agent
        """
        await self._aensure_session()
        request = UserInput(message=message)
        if thread_id:
            request.thread_id = thread_id

        # Prepare headers with session cookie
        headers = self._headers.copy()
        if self.session_cookie:
            headers["Cookie"] = self.session_cookie
            print(f"Adding session cookie to headers: {self.session_cookie}")

        print(f"Request headers with cookie: {headers}")
        response = await self._async_client.post(
            f"{self.base_url}/invoke",
            json=request.model_dump(),
            headers=headers,
        )
        print(f"Request sent to: {response.request.url}")
        print(f"Request headers sent: {dict(response.request.headers)}")
        print(f"Response headers: {dict(response.headers)}")
        print(f"Invoke response status: {response.status_code}")
        if response.status_code == 200:
            return ChatMessage.model_validate(response.json())
        raise Exception(f"Error: {response.status_code} - {response.text}")

    def invoke(
        self, message: str, model: str | None = None, thread_id: str | None = None
    ) -> ChatMessage:
        """
        Invoke the agent synchronously. Only the final message is returned.

        Args:
            message (str): The message to send to the agent
            model (str, optional): LLM model to use for the agent
            thread_id (str, optional): Thread ID for continuing a conversation

        Returns:
            ChatMessage: The response from the agent
        """
        self._ensure_session()
        request = UserInput(message=message)
        if thread_id:
            request.thread_id = thread_id

        # Prepare headers with session cookie
        headers = self._headers.copy()
        if self.session_cookie:
            headers["Cookie"] = self.session_cookie

        response = self._client.post(
            f"{self.base_url}/invoke",
            json=request.model_dump(),
            headers=headers,
        )
        if response.status_code == 200:
            return ChatMessage.model_validate(response.json())
        raise Exception(f"Error: {response.status_code} - {response.text}")

    def _parse_stream_line(self, line: str) -> Union[ChatMessage, dict, str, None]:
        line = line.strip()
        print(line)
        if line.startswith("data: "):
            data = line[6:]
            if data == "[DONE]":
                return None
            try:
                parsed = json.loads(data)
            except Exception as e:
                raise Exception(f"Error JSON parsing message from server: {e}")

            event_type = parsed.get("type")

            # Handle new event types
            match event_type:
                case "assistant_start":
                    return {"type": "assistant_start"}
                case "assistant_token":
                    return parsed["content"]  # Return token content directly
                case "assistant_complete":
                    # Convert to ChatMessage for backward compatibility
                    chat_msg = ChatMessage(
                        type="ai",
                        content=parsed["content"],
                        tool_calls=parsed.get("tool_calls", []),
                        run_id=None
                    )
                    return chat_msg
                case "tool_start":
                    return {
                        "type": "tool_start",
                        "tool_name": parsed["tool_name"],
                        "tool_call_id": parsed["tool_call_id"],
                        "tool_input": parsed["tool_input"]
                    }
                case "tool_token":
                    return {
                        "type": "tool_token",
                        "tool_call_id": parsed["tool_call_id"],
                        "content": parsed["content"]
                    }
                case "tool_end":
                    # Convert to ChatMessage for backward compatibility
                    chat_msg = ChatMessage(
                        type="tool",
                        content=parsed["tool_output"],
                        tool_call_id=parsed["tool_call_id"],
                        tool_status=parsed["status"],
                        run_id=None
                    )
                    return chat_msg
                case "error":
                    raise Exception(parsed["error_message"])
                case "approval_request":
                    return {
                        "type": "approval_request",
                        "tool_name": parsed["tool_name"],
                        "tool_call_id": parsed["tool_call_id"],
                        "tool_input": parsed["tool_input"],
                        "message": parsed["message"]
                    }
                case "keep_alive":
                    return {"type": "keep_alive"}
                case "stream_end":
                    return None
                case _:
                    # Fallback for backward compatibility with old event format
                    if event_type == "message":
                        try:
                            return ChatMessage.model_validate(parsed["content"])
                        except Exception as e:
                            raise Exception(f"Server returned invalid message: {e}")
                    elif event_type == "token":
                        return parsed["content"]
                    else:
                        return parsed
        return None

    def stream(
        self,
        message: str,
        model: str | None = None,
        thread_id: str | None = None,
        stream_tokens: bool = True,
    ) -> Generator[Union[ChatMessage, dict, str], None, None]:
        """
        Stream the agent's response synchronously.

        Each intermediate message of the agent process is yielded as a ChatMessage.
        If stream_tokens is True (the default value), the response will also yield
        content tokens from streaming models as they are generated.

        Args:
            message (str): The message to send to the agent
            model (str, optional): LLM model to use for the agent
            thread_id (str, optional): Thread ID for continuing a conversation
            stream_tokens (bool, optional): Stream tokens as they are generated
                Default: True

        Returns:
            Generator[ChatMessage | str, None, None]: The response from the agent
        """
        self._ensure_session()
        request = StreamInput(message=message, stream_tokens=stream_tokens)
        if thread_id:
            request.thread_id = thread_id

        # Prepare headers with session cookie
        headers = self._headers.copy()
        if self.session_cookie:
            headers["Cookie"] = self.session_cookie

        with self._client.stream(
            "POST",
            f"{self.base_url}/stream",
            json=request.model_dump(),
            headers=headers,
        ) as response:
            if response.status_code != 200:
                raise Exception(f"Error: {response.status_code} - {response.text}")
            for line in response.iter_lines():
                if line.strip():
                    parsed = self._parse_stream_line(line)
                    if parsed is None:
                        break
                    # On receiving an approval request, we need to yield it to streamlit and stop streaming
                    if isinstance(parsed, dict) and parsed.get("type") == "approval_request":
                        yield parsed
                        break
                    yield parsed

    async def astream(
        self,
        message: str,
        model: str | None = None,
        thread_id: str | None = None,
        stream_tokens: bool = True,
    ) -> AsyncGenerator[Union[ChatMessage, dict, str], None]:
        """
        Stream the agent's response asynchronously.

        Each intermediate message of the agent process is yielded as an AnyMessage.
        If stream_tokens is True (the default value), the response will also yield
        content tokens from streaming modelsas they are generated.

        Args:
            message (str): The message to send to the agent
            model (str, optional): LLM model to use for the agent
            thread_id (str, optional): Thread ID for continuing a conversation
            stream_tokens (bool, optional): Stream tokens as they are generated
                Default: True

        Returns:
            AsyncGenerator[ChatMessage | str, None]: The response from the agent
        """
        await self._aensure_session()
        request = StreamInput(message=message, stream_tokens=stream_tokens)
        if thread_id:
            request.thread_id = thread_id

        # Prepare headers with session cookie
        headers = self._headers.copy()
        if self.session_cookie:
            headers["Cookie"] = self.session_cookie

        async with self._async_client.stream(
            "POST",
            f"{self.base_url}/stream",
            json=request.model_dump(),
            headers=headers,
        ) as response:
                if response.status_code != 200:
                    content = await response.aread()
                    raise Exception(f"Error: {response.status_code} - {content.decode('utf-8')}")
                async for line in response.aiter_lines():
                    if line.strip():
                        parsed = self._parse_stream_line(line)
                        if parsed is None:
                            break
                        # On receiving an approval request, we need to yeild it to streamlit and stop streaming
                        if isinstance(parsed, dict) and parsed["type"] == "approval_request":
                            yield parsed
                        yield parsed

    async def approve_request_and_stream(self, thread_id: str, user_input: ToolCallApproval):
        await self._aensure_session()
        print(f"request: {user_input}")

        # Prepare headers with session cookie
        headers = self._headers.copy()
        if self.session_cookie:
            headers["Cookie"] = self.session_cookie

        async with self._async_client.stream(
            "POST",
            f"{self.base_url}/approval/{thread_id}",
            json=user_input.model_dump(),
            headers=headers,
        ) as response:
                if response.status_code != 200:
                    content = await response.aread()
                    raise Exception(f"Error: {response.status_code} - {content.decode('utf-8')}")
                async for line in response.aiter_lines():
                    if line.strip():
                        parsed = self._parse_stream_line(line)
                        if parsed is None:
                            break
                        # On receiving an approval request, we need to yeild it to streamlit and stop streaming
                        if isinstance(parsed, dict) and parsed["type"] == "approval_request":
                            yield parsed
                        yield parsed

    async def acreate_feedback(
        self, run_id: str, key: str, score: float, kwargs: dict[str, Any] = {}
    ) -> None:
        """
        Create a feedback record for a run.

        This is a simple wrapper for the LangSmith create_feedback API, so the
        credentials can be stored and managed in the service rather than the client.
        See: https://api.smith.langchain.com/redoc#tag/feedback/operation/create_feedback_api_v1_feedback_post
        """
        await self._aensure_session()
        request = Feedback(run_id=run_id, key=key, score=score, kwargs=kwargs)

        # Prepare headers with session cookie
        headers = self._headers.copy()
        if self.session_cookie:
            headers["Cookie"] = self.session_cookie

        response = await self._async_client.post(
            f"{self.base_url}/feedback",
            json=request.model_dump(),
            headers=headers,
        )
        if response.status_code != 200:
            raise Exception(f"Error: {response.status_code} - {response.text}")
        return response.json()
