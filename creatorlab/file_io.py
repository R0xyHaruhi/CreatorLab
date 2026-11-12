"""Small atomic JSON writes with bounded Windows sharing-violation retries."""
import json
import os
import time
import uuid
from pathlib import Path


def atomic_json(path,data):
    dest=Path(path);dest.parent.mkdir(parents=True,exist_ok=True)
    tmp=dest.with_name(dest.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        tmp.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
        for attempt in range(5):
            try:os.replace(tmp,dest);break
            except PermissionError:
                if attempt==4:raise
                time.sleep(.05*(attempt+1))
    finally:tmp.unlink(missing_ok=True)
