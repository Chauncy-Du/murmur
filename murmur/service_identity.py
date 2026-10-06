"""Display the configured serving endpoint separately from the model family."""
from urllib.parse import urlsplit
import re

from .usage import is_local_endpoint
from .projecthub import is_projecthub


def model_source_label(endpoint):
    """No discovery or I/O; never display URL credentials, path or query."""
    try:
        parsed=urlsplit(endpoint.strip())
        host=(parsed.hostname or '').lower().rstrip('.')
        port=parsed.port
        if not host or not re.fullmatch(r'[a-z0-9.:-]+',host):return 'Custom API'
        if is_local_endpoint(endpoint):return 'Local'
        if parsed.scheme=='https' and port in (None,443):
            if is_projecthub(endpoint):return 'ProjectHub Private'
            official={'api.deepseek.com':'DeepSeek Official',
                      'api.openai.com':'OpenAI Official',
                      'dashscope.aliyuncs.com':'Bailian Official',
                      'dashscope-intl.aliyuncs.com':'Bailian Official'}
            if host in official:return official[host]
        return 'Custom API · '+host+((':'+str(port)) if port is not None else '')
    except (ValueError,TypeError,AttributeError):
        return 'Custom API'
