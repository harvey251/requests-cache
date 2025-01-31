"""Classes to wrap cached response objects"""
from datetime import datetime, timedelta, timezone
from logging import getLogger
from typing import List, Optional, Tuple, Union

from attr import define, field
from requests import Response as OriginalResponse
from requests.cookies import RequestsCookieJar
from requests.structures import CaseInsensitiveDict

from ..cache_control import ExpirationTime, get_expiration_datetime
from . import CachedHTTPResponse, CachedRequest

DATETIME_FORMAT = '%Y-%m-%d %H:%M:%S %Z'  # Format used for __str__ only
DO_NOT_CACHE = 0

# Make a slotted copy of requests.Response to subclass
Response = define(slots=True)(OriginalResponse)
HeaderList = List[Tuple[str, str]]

logger = getLogger(__name__)


@define(auto_attribs=False)
class CachedResponse(Response):
    """A serializable dataclass that emulates :py:class:`requests.Response`. Public attributes and
    methods on CachedResponse objects will behave the same as those from the original response, but
    with different internals optimized for serialization.

    This means doing some pre- and post-initialization steps common to all serializers, such as
    breaking nested objects down into their basic attributes and lazily re-initializing them, which
    saves a bit of memory and deserialization steps when those objects aren't accessed.
    """

    _content: bytes = field(default=None)
    url: str = field(default=None)
    status_code: int = field(default=0)
    cookies: RequestsCookieJar = field(factory=dict)
    created_at: datetime = field(factory=datetime.utcnow)
    elapsed: timedelta = field(factory=timedelta)
    expires: datetime = field(default=None)
    encoding: str = field(default=None)
    headers: CaseInsensitiveDict = field(factory=dict)
    history: List = field(factory=list)
    reason: str = field(default=None)
    request: CachedRequest = field(factory=CachedRequest)
    raw: CachedHTTPResponse = field(factory=CachedHTTPResponse, repr=False)

    def __attrs_post_init__(self):
        """Re-initialize raw response body after deserialization"""
        if self.raw._body is None and self._content is not None:
            self.raw.reset(self._content)

    @classmethod
    def from_response(cls, original_response: Response, **kwargs):
        """Create a CachedResponse based on an original response object"""
        obj = cls(**kwargs)

        # Copy basic attributes
        for k in Response.__attrs__:
            setattr(obj, k, getattr(original_response, k, None))

        # Store request and raw response
        obj.request = CachedRequest.from_request(original_response.request)
        obj.raw = CachedHTTPResponse.from_response(original_response)

        # Store response body, which will have been read & decoded by requests.Response by now
        obj._content = original_response.content

        # Copy redirect history, if any; avoid recursion by not copying redirects of redirects
        obj.history = []
        if not obj.is_redirect:
            for redirect in original_response.history:
                obj.history.append(cls.from_response(redirect))

        return obj

    @property
    def _content_consumed(self):
        """For compatibility with Response; will always be True for a cached response"""
        return True

    @_content_consumed.setter
    def _content_consumed(self, value):
        pass

    @property
    def from_cache(self) -> bool:
        return True

    @property
    def is_expired(self) -> bool:
        """Determine if this cached response is expired"""
        return self.expires is not None and datetime.utcnow() >= self.expires

    def revalidate(self, expire_after: ExpirationTime) -> bool:
        """Set a new expiration for this response, and determine if it is now expired"""
        self.expires = get_expiration_datetime(expire_after)
        return self.is_expired

    def reset(self):
        if self.raw:
            self.raw.reset()

    @property
    def size(self) -> int:
        """Get the size of the response body in bytes"""
        return len(self.content) if self.content else 0

    # TODO: Behavior will be different for slotted classes
    # def __getstate__(self):
    #     """Override pickling behavior in ``requests.Response.__getstate__``"""
    #     return self.__dict__

    def __str__(self):
        return (
            f'request: {self.request}, response: {self.status_code} '
            f'({format_file_size(self.size)}), created: {format_datetime(self.created_at)}, '
            f'expires: {format_datetime(self.expires)} ({"stale" if self.is_expired else "fresh"})'
        )


AnyResponse = Union[Response, CachedResponse]


def format_datetime(value: Optional[datetime]) -> str:
    """Get a formatted datetime string in the local time zone"""
    if not value:
        return "N/A"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone().strftime(DATETIME_FORMAT)


def format_file_size(n_bytes: int) -> str:
    """Convert a file size in bytes into a human-readable format"""
    filesize = float(n_bytes or 0)

    def _format(unit):
        return f'{int(filesize)} {unit}' if unit == 'bytes' else f'{filesize:.2f} {unit}'

    for unit in ['bytes', 'KiB', 'MiB', 'GiB']:
        if filesize < 1024 or unit == 'GiB':
            return _format(unit)
        filesize /= 1024


def set_response_defaults(response: AnyResponse) -> AnyResponse:
    """Set some default CachedResponse values on a requests.Response object, so they can be
    expected to always be present
    """
    if not isinstance(response, CachedResponse):
        response.created_at = None
        response.expires = None
        response.from_cache = False
        response.is_expired = False
    return response
