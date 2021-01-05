from datetime import datetime
from typing import Dict, List, Union

InvFinalItem = Dict[str, Union[str, int, List[Dict[str, Union[int, datetime]]]]]
InvBooster = Dict[str, Dict[int, Dict[int, InvFinalItem]]]
InvFinal = Dict[str, Dict[int, InvFinalItem]]
InvRaw = Dict[str, Dict[int, Dict[str, Union[str, int]]]]
