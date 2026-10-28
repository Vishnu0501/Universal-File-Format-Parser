from dataclasses import dataclass, field
from enum import Enum
from typing import Any,Optional

class RecordType(str,Enum):
    DATA = "data"
    ERROR = "error"
    WARNING = "warning"

class Severity(str,Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

@dataclass
class Record:
    type: RecordType
    format: str
    content: Optional[Any] = None
    offset: Optional[int] = None
    reason: Optional[str] = None
    severity: Optional[Severity] = None
    metadata: dict = field(default_factory=dict)
    

'''"This is the single data contract for the entire library. Every parser, every error, 
every security warning produces one of these. type and format are the only required fields.

content holds the parsed payload for DATA records — a dict for CSV rows, a 2D array for XLSX sheets, 
a string for PDF pages.

offset is the byte position in the original file where an error occurred — important for 
corruption recovery.

reason is the human-readable error message.

severity is only set on WARNING records — LOW through CRITICAL.

metadata is a free dict — page number for PDFs, slide number for PPTX, sheet name for XLSX, 
segment timestamps for audio.

Why field(default_factory=dict) and not just = {}? Because Python evaluates default 
arguments once at class definition time. If we used = {}, all Record instances 
would share the same dict object — mutating one would mutate all. default_factory creates 
a fresh dict for each instance."'''