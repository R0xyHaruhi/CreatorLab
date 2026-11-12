"""User-started browser installation with a single task lock."""
from pathlib import Path
import os
import subprocess
import sys
from creatorlab.maintenance import database_gate
from creatorlab.sync_browser import status_write


def install(root):
    local=Path(root)/'local';local.mkdir(exist_ok=True)
    with database_gate(local/'browser-install',timeout=.2):
        status=local/'browser_install_status.json'
        status_write(status,state='installing',pid=os.getpid(),info='正在安装导入浏览器')
        with open(local/'browser_install.log','a',encoding='utf-8') as log:
            result=subprocess.run([sys.executable,'-m','playwright','install','chromium'],stdout=log,stderr=log)
        status_write(status,state='completed' if result.returncode==0 else 'error',info='浏览器已安装' if result.returncode==0 else '下载未成功，请检查网络后重试；作品数据已保留')
        return result.returncode


if __name__=='__main__':raise SystemExit(install(Path(__file__).resolve().parents[1]))
