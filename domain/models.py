from dataclasses import dataclass
from datetime import date

@dataclass
class Operator:
    id:      int
    op_name: str

@dataclass
class Record:
    id:           int
    op_id:        int
    printer_name: str
    filament:     str
    consumption:  float
    date:         date
    comments:     str